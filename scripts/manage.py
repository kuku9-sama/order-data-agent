import argparse
import csv
import sqlite3
from pathlib import Path

from order_agent.config import DB_PATH
from order_agent.db import generate

p = argparse.ArgumentParser()
p.add_argument("command", choices=["generate", "templates"])
p.add_argument("--db", default=str(DB_PATH))
a = p.parse_args()
if a.command == "generate":
    generate(a.db)
    print("已生成固定种子合成数据：" + a.db)
else:
    with sqlite3.connect(Path(a.db).resolve().as_uri() + "?mode=ro", uri=True) as con:
        for table in ["products", "orders", "order_items", "refunds"]:
            cur = con.execute(f"SELECT * FROM {table} LIMIT 0")
            with open(f"data/sample/{table}.csv", "w", newline="") as f:
                csv.writer(f, lineterminator="\n").writerow([r[0] for r in cur.description])
