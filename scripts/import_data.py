import argparse
from pathlib import Path

from order_agent.config import DB_PATH
from order_agent.imports import import_csv

p = argparse.ArgumentParser(description="本地独立CSV导入，默认仅预览")
p.add_argument("--directory", required=True)
p.add_argument("--commit", action="store_true")
a = p.parse_args()
files = {
    t: (Path(a.directory) / f"{t}.csv").read_text(encoding="utf-8-sig")
    for t in ["products", "orders", "order_items", "refunds"]
    if (Path(a.directory) / f"{t}.csv").exists()
}
print(import_csv(DB_PATH, files, preview=not a.commit))
