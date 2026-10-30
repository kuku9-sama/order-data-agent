import json
import sqlite3
import time
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope

from .config import TABLES


class QueryDenied(ValueError):
    pass


FUNCTIONS = {
    "sum",
    "count",
    "avg",
    "min",
    "max",
    "coalesce",
    "substr",
    "date",
    "strftime",
    "abs",
    "round",
    "like",
    "lower",
    "upper",
}


def check_sql(sql):
    try:
        trees = sqlglot.parse(sql, read="sqlite")
        if len(trees) != 1 or not isinstance(trees[0], exp.Query):
            raise QueryDenied("仅允许单条SELECT查询")
        tree = trees[0]
        for node in tree.walk():
            if isinstance(
                node, (exp.Insert, exp.Delete, exp.Update, exp.Create, exp.Drop, exp.Command, exp.Into)
            ):
                raise QueryDenied("禁止写入或管理语句")
        for scope in traverse_scope(tree):
            for source in scope.sources.values():
                if isinstance(source, exp.Table) and (
                    source.name not in TABLES or source.db or source.catalog
                ):
                    raise QueryDenied("表不在许可结构中")
        if (
            any(isinstance(n, exp.CTE) and n.args.get("recursive") for n in tree.walk())
            or tree.find(exp.With)
            and tree.find(exp.With).args.get("recursive")
        ):
            raise QueryDenied("不允许递归CTE")
    except QueryDenied:
        raise
    except Exception as e:
        raise QueryDenied("SQL解析失败") from e


def query(path, sql, params=None, timeout=3.0, max_bytes=100000):
    check_sql(sql)
    started = time.monotonic()
    con = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        con.execute("PRAGMA query_only=ON")

        def authorize(action, arg1, arg2, db, trigger):
            if action == sqlite3.SQLITE_SELECT:
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_READ and arg1 in TABLES:
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in FUNCTIONS:
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY

        con.set_authorizer(authorize)
        con.set_progress_handler(lambda: int(time.monotonic() - started > timeout), 1000)
        cur = con.execute(sql, params or {})
        names = [c[0] for c in cur.description]
        rows = cur.fetchmany(201)
        truncated = len(rows) > 200
        rows = rows[:200]
        while rows and len(json.dumps(rows, ensure_ascii=False).encode()) > max_bytes:
            rows.pop()
            truncated = True
        return {
            "columns": names,
            "rows": rows,
            "truncated": truncated,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
        }
    finally:
        con.close()


def structure(path):
    with sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True) as con:
        return {t: [r[1] for r in con.execute(f"PRAGMA table_info({t})")] for t in sorted(TABLES)}
