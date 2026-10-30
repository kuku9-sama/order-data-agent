import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE products(id INTEGER PRIMARY KEY,sku TEXT UNIQUE NOT NULL,name TEXT NOT NULL);
CREATE TABLE orders(id INTEGER PRIMARY KEY,external_id TEXT NOT NULL,shop TEXT NOT NULL,currency TEXT CHECK(currency='CNY') NOT NULL,status TEXT CHECK(status IN ('paid','cancelled')) NOT NULL,paid_at TEXT NOT NULL,paid_cents INTEGER CHECK(paid_cents>=0) NOT NULL,UNIQUE(external_id,shop));
CREATE TABLE order_items(id INTEGER PRIMARY KEY,order_id INTEGER NOT NULL REFERENCES orders(id),product_id INTEGER NOT NULL REFERENCES products(id),quantity INTEGER CHECK(quantity>0) NOT NULL,paid_cents INTEGER CHECK(paid_cents>=0) NOT NULL);
CREATE TABLE refunds(id INTEGER PRIMARY KEY,item_id INTEGER NOT NULL REFERENCES order_items(id),status TEXT CHECK(status IN ('success','pending')) NOT NULL,amount_cents INTEGER CHECK(amount_cents>=0) NOT NULL,completed_at TEXT NOT NULL);
"""


def validate(con):
    if con.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError("外键错误")
    if con.execute(
        "SELECT o.id FROM orders o LEFT JOIN order_items i ON o.id=i.order_id GROUP BY o.id HAVING o.paid_cents != COALESCE(SUM(i.paid_cents),0)"
    ).fetchone():
        raise ValueError("订单与明细金额不一致")
    if con.execute(
        "SELECT i.id FROM order_items i JOIN refunds r ON i.id=r.item_id WHERE r.status='success' GROUP BY i.id HAVING SUM(r.amount_cents)>i.paid_cents"
    ).fetchone():
        raise ValueError("成功退款超过明细实付")


def generate(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError("数据库已存在，拒绝覆盖")
    rng = random.Random(42)
    with sqlite3.connect(path) as con:
        con.execute("PRAGMA foreign_keys=ON")
        con.executescript(SCHEMA)
        con.executemany(
            "INSERT INTO products VALUES(?,?,?)",
            [(i, f"SKU{i:03}", f"合成商品{i:03}") for i in range(1, 101)],
        )
        item_id = refund_id = 0
        for oid in range(1, 1001):
            date = (
                datetime(2025, 1, 1) + timedelta(days=(oid - 1) % 59, hours=oid % 24)
            ).isoformat() + "+08:00"
            status = "cancelled" if oid % 10 == 0 else "paid"
            amounts = [rng.randint(100, 20000) if status == "paid" else 0 for _ in range(2)]
            con.execute(
                "INSERT INTO orders VALUES(?,?,?,?,?,?,?)",
                (oid, f"DEMO{oid:05}", f"店铺{oid % 3 + 1}", "CNY", status, date, sum(amounts)),
            )
            for amount in amounts:
                item_id += 1
                con.execute(
                    "INSERT INTO order_items VALUES(?,?,?,?,?)",
                    (item_id, oid, rng.randint(1, 100), rng.randint(1, 3), amount),
                )
                if status == "paid" and oid % 7 == 0:
                    for part in (amount // 4, amount // 5):
                        refund_id += 1
                        con.execute(
                            "INSERT INTO refunds VALUES(?,?,?,?,?)",
                            (
                                refund_id,
                                item_id,
                                "success",
                                part,
                                (datetime.fromisoformat(date) + timedelta(days=5)).isoformat(),
                            ),
                        )
        validate(con)
