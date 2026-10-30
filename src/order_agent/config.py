import os
from pathlib import Path

DB_PATH = Path(os.getenv("ORDER_DB", "runtime/orders.db"))
CUTOFF = "2025-03-15T00:00:00+08:00"
VERSION = "synthetic-v1-seed42"
TABLES = {"products", "orders", "order_items", "refunds"}
METRICS = "人民币整数分；支付期为左闭右开区间（Asia/Shanghai）。排除取消订单。退款先按明细聚合；净额=支付期销售额减截至2025-03-15的成功退款，不是利润。"
