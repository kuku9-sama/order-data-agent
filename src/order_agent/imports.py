import csv
import io
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .config import TABLES
from .db import validate

ORDER = ["products", "orders", "order_items", "refunds"]


def import_csv(path, files, preview=True):
    if not files or set(files) - TABLES:
        raise ValueError("仅允许四类业务表CSV")
    parsed = {}
    for table, text in files.items():
        if len(text.encode("utf-8")) > 2_000_000 or "\x00" in text:
            raise ValueError("文件过大或包含非法编码")
        reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")), strict=True)
        rows = list(reader)
        if len(rows) > 10000:
            raise ValueError("单表最多10000行")
        parsed[table] = (reader.fieldnames, rows)
    path = Path(path)
    backup = path.parent / "backups" / f"{uuid4().hex}.db"
    if not preview:
        backup.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as source, sqlite3.connect(backup) as target:
            source.backup(target)
    con = sqlite3.connect(path)
    report = {"inserted": 0, "skipped": 0, "preview": preview, "backup": str(backup) if not preview else None}
    try:
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("BEGIN IMMEDIATE")
        for table in ORDER:
            if table not in parsed:
                continue
            headers, rows = parsed[table]
            info = con.execute(f"PRAGMA table_info({table})").fetchall()
            columns = [r[1] for r in info]
            if headers != columns:
                raise ValueError(f"{table}表头必须为" + ",".join(columns))
            for row in rows:
                if None in row or any(v is None for v in row.values()):
                    raise ValueError("CSV列数错误")
                values = []
                for col in info:
                    name, kind = col[1], col[2]
                    value = row[name]
                    if kind == "INTEGER":
                        if not value.isascii() or not value.isdecimal():
                            raise ValueError(f"{name}须为非负整数")
                        value = int(value)
                    if name in ("paid_at", "completed_at"):
                        dt = datetime.fromisoformat(value)
                        if dt.utcoffset() is None or dt.utcoffset().total_seconds() != 28800:
                            raise ValueError("时间必须带+08:00时区")
                        value = dt.isoformat()
                    values.append(value)
                old = con.execute(f"SELECT * FROM {table} WHERE id=?", (values[0],)).fetchone()
                if old:
                    if tuple(values) != old:
                        raise ValueError(f"{table}主键冲突，事务已回滚")
                    report["skipped"] += 1
                else:
                    con.execute(f"INSERT INTO {table} VALUES(" + ",".join("?" for _ in columns) + ")", values)
                    report["inserted"] += 1
        validate(con)
        if preview:
            con.rollback()
        else:
            con.commit()
        return report
    except (sqlite3.Error, ValueError, csv.Error) as e:
        con.rollback()
        raise ValueError("导入失败：" + str(e)) from e
    finally:
        con.close()
