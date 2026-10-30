import hashlib
import re
import threading
from collections import OrderedDict
from uuid import uuid4

from .config import CUTOFF, METRICS
from .models import money
from .tools import query, structure


class OfflineModel:
    """确定性中文示例规划器，不是通用大模型。"""

    def plan(self, question, context):
        if any(
            w in question.lower()
            for w in ["delete", "drop", "attach", "pragma", "删除", "修改", "密码", "利润", "汇率", "手续费"]
        ):
            return {"status": "refused", "answer": "不支持写入、敏感操作或缺少口径的利润/汇率计算。"}
        if any(w in question for w in ["收入", "赚了", "销售情况", "怎么样"]) and not any(
            w in question for w in ["销售额", "退款额", "净额"]
        ):
            return {"status": "clarify", "answer": "请明确要统计销售额、退款额还是支付期净额。"}
        metric = next(
            (m for m in ["净额", "退款", "销量", "销售额", "异常", "明细", "按日", "店铺"] if m in question),
            context.get("metric"),
        )
        if not metric:
            return {
                "status": "clarify",
                "answer": "离线演示支持销售排行、退款排行、净额、按日、店铺、异常及明细，请指定指标。",
            }
        month_match = re.search(r"(?:2025年)?([12])月", question)
        if re.search(r"202[0-46-9]|[3-9]月|1[012]月", question):
            return {"status": "clarify", "answer": "合成数据仅覆盖2025年1—2月，请指定该范围。"}
        month = int(month_match.group(1)) if month_match else context.get("month", 0)
        start, end = {
            0: ("2025-01-01", "2025-03-01"),
            1: ("2025-01-01", "2025-02-01"),
            2: ("2025-02-01", "2025-03-01"),
        }[month]
        shop_match = re.search(r"店铺(\d+)", question)
        shop = "店铺" + shop_match.group(1) if shop_match else context.get("shop", "")
        group_by = (
            "day"
            if "按日" in question
            else "shop"
            if "店铺" in question and not shop_match
            else "product"
            if "商品" in question
            else context.get("group_by", "product")
        )
        if group_by == "shop" and "店铺" in question and not shop_match:
            shop = ""
        top_match = re.search(r"(?:前|top\s*)(\d+)", question, re.IGNORECASE)
        top = min(max(int(top_match.group(1)), 1), 200) if top_match else context.get("top", 10)
        if group_by == "day" and "按日" in question and not top_match:
            top = 200
        params = {
            "start": start + "T00:00:00+08:00",
            "end": end + "T00:00:00+08:00",
            "cutoff": CUTOFF,
            "shop": shop,
            "top": top,
        }
        where = "o.status='paid' AND o.paid_at>=:start AND o.paid_at<:end AND (:shop='' OR o.shop=:shop)"
        prefix = "WITH r AS (SELECT item_id,SUM(amount_cents) refunded FROM refunds WHERE status='success' AND completed_at<:cutoff GROUP BY item_id) "
        if metric == "退款":
            refund_group = (
                "substr(r.completed_at,1,10)"
                if group_by == "day"
                else "o.shop"
                if group_by == "shop"
                else "p.name"
            )
            sql = f"SELECT {refund_group} AS label,SUM(r.amount_cents) AS refund_cents FROM refunds r JOIN order_items i ON i.id=r.item_id JOIN products p ON p.id=i.product_id JOIN orders o ON o.id=i.order_id WHERE r.status='success' AND r.completed_at>=:start AND r.completed_at<:end AND (:shop='' OR o.shop=:shop) GROUP BY {refund_group} ORDER BY refund_cents DESC,label LIMIT :top"
        elif metric in ("明细", "异常"):
            sql = (
                "SELECT o.external_id,o.shop,o.status,o.paid_at,o.paid_cents FROM orders o WHERE "
                + ("o.status='cancelled'" if metric == "异常" else where)
                + " AND o.paid_at>=:start AND o.paid_at<:end AND (:shop='' OR o.shop=:shop) ORDER BY o.id LIMIT :top"
            )
        else:
            group = (
                "substr(o.paid_at,1,10)"
                if group_by == "day"
                else "o.shop"
                if group_by == "shop"
                else "p.name"
            )
            value = (
                "SUM(i.quantity)"
                if metric == "销量"
                else "SUM(i.paid_cents-COALESCE(r.refunded,0))"
                if metric == "净额"
                else "SUM(i.paid_cents)"
            )
            alias = "quantity" if metric == "销量" else "net_cents" if metric == "净额" else "sales_cents"
            sql = (
                prefix
                + f"SELECT {group} AS label,{value} AS {alias} FROM order_items i JOIN orders o ON o.id=i.order_id JOIN products p ON p.id=i.product_id LEFT JOIN r ON r.item_id=i.id WHERE {where} GROUP BY {group} ORDER BY {alias} DESC,label LIMIT :top"
            )
        return {
            "status": "query",
            "sql": sql,
            "params": params,
            "context": {"metric": metric, "month": month, "shop": shop, "top": top, "group_by": group_by},
        }


class Agent:
    def __init__(self, path):
        self.path = path
        self.model = OfflineModel()
        self.sessions = OrderedDict()
        self.lock = threading.Lock()

    def chat(self, question, session_id):
        with self.lock:
            trace = uuid4().hex
            structure(self.path)
            plan = self.model.plan(question, self.sessions.get(session_id, {}))
            base = {
                "trace_id": trace,
                "dataset_version": hashlib.sha256(self.path.read_bytes()).hexdigest()[:16],
                "mode": "offline",
                "cutoff": CUTOFF,
                "metrics": METRICS,
            }
            if plan["status"] != "query":
                return base | plan
            result = query(self.path, plan["sql"], plan["params"])
            self.sessions[session_id] = plan["context"]
            self.sessions.move_to_end(session_id)
            if len(self.sessions) > 100:
                self.sessions.popitem(last=False)
            answer = (
                "未查询到符合条件的数据。" if not result["rows"] else f"查询返回{len(result['rows'])}行。"
            )
            if result["rows"]:
                row = result["rows"][0]
                value = money(row[-1]) + "元" if result["columns"][-1].endswith("_cents") else str(row[-1])
                answer += f"首行：{row[0]}，{value}。"
            return base | dict(
                status="ok", answer=answer, sql=plan["sql"], params=plan["params"], tool_calls=3, **result
            )
