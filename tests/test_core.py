import csv
import io
import sqlite3

import pytest

from order_agent.agent import Agent
from order_agent.export import export_csv
from order_agent.imports import import_csv
from order_agent.models import money
from order_agent.tools import QueryDenied, query


def test_money():
    assert money(100000000001) == "1000000000.01"


def test_invariants_and_net(db):
    with sqlite3.connect(db) as c:
        sales = c.execute("SELECT SUM(paid_cents) FROM orders WHERE status='paid'").fetchone()[0]
        refunds = c.execute("SELECT SUM(amount_cents) FROM refunds WHERE status='success'").fetchone()[0]
    a = Agent(db)
    r = a.chat("净额前100名", "net")
    assert sum(row[1] for row in r["rows"]) == sales - refunds
    r = a.chat("销售额前100名", "sales")
    assert sum(row[1] for row in r["rows"]) == sales


def test_boundary_and_cancelled(db):
    sql = "SELECT COUNT(*) FROM orders WHERE paid_at>=:s AND paid_at<:e"
    jan = query(db, sql, {"s": "2025-01-01", "e": "2025-02-01"})["rows"][0][0]
    feb = query(db, sql, {"s": "2025-02-01", "e": "2025-03-01"})["rows"][0][0]
    assert jan + feb == 1000
    assert query(db, "SELECT COUNT(*) FROM orders WHERE status='cancelled'")["rows"] == [(100,)]


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM orders",
        "SELECT * FROM sqlite_master",
        "SELECT * FROM unknown",
        "SELECT 1; SELECT 2",
        "PRAGMA database_list",
        "ATTACH DATABASE :p AS x",
        "WITH x AS (SELECT * FROM sqlite_master) SELECT * FROM x",
        "SELECT load_extension(:p)",
        "SELECT randomblob(1000000000)",
        "WITH RECURSIVE x(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM x) SELECT * FROM x",
        "SELECT * FROM main.orders",
    ],
)
def test_denials(db, sql):
    with pytest.raises((QueryDenied, sqlite3.DatabaseError)):
        query(db, sql, {"p": "/tmp/forbidden"})


def test_cte_and_truncation(db):
    r = query(db, "WITH x AS (SELECT * FROM orders) SELECT * FROM x")
    assert len(r["rows"]) == 200 and r["truncated"]
    assert query(db, "SELECT name FROM products", max_bytes=10)["truncated"]


def test_timeout(db):
    with pytest.raises(sqlite3.OperationalError, match="interrupted"):
        query(
            db,
            "SELECT SUM(a.quantity*b.quantity*c.quantity) FROM order_items a CROSS JOIN order_items b CROSS JOIN order_items c",
            timeout=0.001,
        )


def dump(db, table):
    with sqlite3.connect(db) as c:
        cur = c.execute(f"SELECT * FROM {table}")
        s = io.StringIO()
        w = csv.writer(s)
        w.writerow([col[0] for col in cur.description])
        w.writerows(cur.fetchall())
        return s.getvalue()


def test_duplicate_import(db):
    text = dump(db, "products")
    assert import_csv(db, {"products": text}, True)["skipped"] == 100
    r = import_csv(db, {"products": text}, False)
    assert r["skipped"] == 100 and r["backup"]


def test_rollback_conflict(db):
    text = "id,sku,name\n101,NEW,new\n1,BAD,conflict\n"
    with pytest.raises(ValueError):
        import_csv(db, {"products": text}, False)
    assert query(db, "SELECT COUNT(*) FROM products")["rows"][0][0] == 100


@pytest.mark.parametrize(
    "text",
    [
        "id,external_id,shop,currency,status,paid_at,paid_cents\n1001,X,S,CNY,paid,not-date,10\n",
        "id,external_id,shop,currency,status,paid_at,paid_cents\n1001,X,S,CNY,paid,2025-01-01T00:00:00+08:00,1.5\n",
    ],
)
def test_invalid_import(db, text):
    with pytest.raises(ValueError):
        import_csv(db, {"orders": text}, False)


def test_fk_import(db):
    with pytest.raises(ValueError):
        import_csv(
            db, {"order_items": "id,order_id,product_id,quantity,paid_cents\n2001,99999,1,1,0\n"}, False
        )


def test_chat_and_context(db):
    a = Agent(db)
    assert a.chat("收入多少", "a")["status"] == "clarify"
    assert a.chat("删除订单", "a")["status"] == "refused"
    r = a.chat("1月销售额前5名", "a")
    assert len(r["rows"]) == 5
    r = a.chat("改成2月前3名", "a")
    assert len(r["rows"]) == 3 and r["params"]["start"].startswith("2025-02")
    assert a.chat("1月退款排行", "b")["rows"]
    assert a.chat("店铺99销售额", "c")["rows"] == []


def test_export():
    assert "'=evil" in export_csv(["name"], [["=evil"]])


def test_api(db, monkeypatch):
    from fastapi.testclient import TestClient

    from order_agent import api

    monkeypatch.setattr(api, "agent", Agent(db))
    with TestClient(api.app, raise_server_exceptions=False) as c:
        assert c.get("/health").status_code == 200
        assert c.get("/ready").status_code == 200
        assert c.post("/chat", json={"question": "1月销售额"}).json()["status"] == "ok"
        assert c.post("/imports", json={"files": {}, "preview": False}).status_code == 400
        assert c.post("/chat", json={"question": ""}).status_code == 422


def test_dataset_overview_is_real_readonly_data(db, monkeypatch):
    from fastapi.testclient import TestClient

    from order_agent import api

    monkeypatch.setattr(api, "agent", Agent(db))
    with TestClient(api.app) as client:
        result = client.get("/dataset")
        assert result.status_code == 200
        data = result.json()
        assert data["orders"] == 1000 and data["products"] == 100
        assert data["date_start"].startswith("2025-01-01")
        with sqlite3.connect(db) as con:
            sales = con.execute("SELECT SUM(paid_cents) FROM orders WHERE status='paid'").fetchone()[0]
            refunds = con.execute("SELECT SUM(amount_cents) FROM refunds WHERE status='success'").fetchone()[
                0
            ]
        assert data["sales_cents"] == sales and data["refund_cents"] == refunds


def test_daily_sales_and_month_followup(db):
    a = Agent(db)
    result = a.chat("2月按日销售额", "daily")
    assert len(result["rows"]) == 28
    assert all(row[0].startswith("2025-02-") for row in result["rows"])
    with sqlite3.connect(db) as con:
        reference = con.execute(
            "SELECT substr(paid_at,1,10),SUM(paid_cents) FROM orders WHERE status='paid' AND paid_at>='2025-02-01' AND paid_at<'2025-03-01' GROUP BY substr(paid_at,1,10)"
        ).fetchall()
    assert dict(result["rows"]) == dict(reference)
    january = a.chat("改成1月", "daily")
    assert len(january["rows"]) == 31
    assert all(row[0].startswith("2025-01-") for row in january["rows"])


def test_shop_net_is_grouped_by_shop(db):
    result = Agent(db).chat("店铺净额前10名", "shops")
    assert {row[0] for row in result["rows"]} == {"店铺1", "店铺2", "店铺3"}
    with sqlite3.connect(db) as con:
        reference = con.execute(
            "SELECT o.shop,SUM(i.paid_cents-(SELECT COALESCE(SUM(r.amount_cents),0) FROM refunds r WHERE r.item_id=i.id AND r.status='success' AND r.completed_at<'2025-03-15T00:00:00+08:00')) FROM orders o JOIN order_items i ON i.order_id=o.id WHERE o.status='paid' GROUP BY o.shop"
        ).fetchall()
    assert dict(result["rows"]) == dict(reference)


def test_daily_refund_uses_completion_date(db):
    result = Agent(db).chat("2月按日退款额", "refunds")
    with sqlite3.connect(db) as con:
        reference = con.execute(
            "SELECT substr(completed_at,1,10),SUM(amount_cents) FROM refunds WHERE status='success' AND completed_at>='2025-02-01' AND completed_at<'2025-03-01' GROUP BY substr(completed_at,1,10)"
        ).fetchall()
    assert dict(result["rows"]) == dict(reference)
