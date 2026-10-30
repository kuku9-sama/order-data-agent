import uuid

import httpx
import pandas as pd
import streamlit as st

from order_agent.export import export_csv

st.set_page_config(page_title="中文订单分析助手", layout="wide")
st.title("中文订单分析助手")
st.write("查询商品销售、退款与订单明细，查看数据和对应 SQL。")
st.caption("示例数据 · 2025年1—2月支付订单 · 统计截止 2025-03-15 · 人民币")
if "session" not in st.session_state:
    st.session_state.session = uuid.uuid4().hex
api = "http://127.0.0.1:8000"
with st.sidebar:
    st.subheader("数据与运行模式")
    st.write("数据来源：固定种子合成订单")
    try:
        mode = httpx.get(api + "/health", timeout=3).json().get("model_mode")
        st.write("查询模式：" + ("DeepSeek" if mode == "deepseek" else "本地示例"))
    except httpx.HTTPError:
        st.warning("API 尚未连接")
    st.caption("本地示例模式支持预设的中文查询类型。金额和排名均来自实际数据库查询。")
question = st.text_input("输入问题", placeholder="例如：1月商品销售额前10名")
st.caption("示例：2月按日销售额 / 店铺1净额前5名 / 1月异常订单 / 收入多少（追问） / 删除订单（拒绝）")
if st.button("查询", type="primary") and question:
    try:
        response = httpx.post(
            api + "/chat", json={"question": question, "session_id": st.session_state.session}, timeout=10
        )
        response.raise_for_status()
        result = response.json()
        st.write(result["answer"])
        st.caption(result["metrics"])
        if "rows" in result:
            df = pd.DataFrame(result["rows"], columns=result["columns"])
            st.dataframe(
                df.head(50).rename(
                    columns={
                        "label": "商品 / 分组",
                        "sales_cents": "销售额（分）",
                        "net_cents": "净额（分）",
                        "refund_cents": "退款额（分）",
                        "quantity": "销量",
                        "name": "商品名称",
                        "external_id": "订单号",
                        "shop": "店铺",
                        "status": "订单状态",
                        "paid_at": "支付时间",
                        "paid_cents": "实付（分）",
                    }
                ),
                hide_index=True,
            )
            st.caption("金额列单位：分；页面最多展示50行。" + ("结果已截断。" if result["truncated"] else ""))
            if len(df.columns) == 2 and len(df):
                if "按日" in question:
                    st.line_chart(df.sort_values(df.columns[0]).set_index(df.columns[0]))
                else:
                    st.bar_chart(df.set_index(df.columns[0]))
            st.download_button(
                "下载查询结果 CSV",
                export_csv(result["columns"], result["rows"]),
                file_name="查询结果.csv",
                mime="text/csv",
            )
            with st.expander("SQL、参数与追踪"):
                st.code(result["sql"], language="sql")
                st.json(
                    {k: result[k] for k in ["params", "trace_id", "elapsed_ms", "dataset_version", "cutoff"]}
                )
    except (httpx.HTTPError, KeyError):
        st.error("查询失败：请检查API是否启动、输入及数据状态。")
with st.expander("本地CSV导入（不会发送到外部模型）"):
    st.caption("按商品→订单→明细→退款顺序，表头见data/sample。预览会执行完整校验并回滚；正式导入先备份。")
    files = {
        t: st.file_uploader(t, type=["csv"], key=t) for t in ["products", "orders", "order_items", "refunds"]
    }
    confirm = st.checkbox("确认仅在本地处理数据并导入")
    for label, preview in [("预览并校验", True), ("事务导入", False)]:
        if st.button(label, disabled=not preview and not confirm):
            try:
                payload = {k: v.getvalue().decode("utf-8-sig") for k, v in files.items() if v}
                r = httpx.post(
                    api + "/imports",
                    json={"files": payload, "preview": preview, "confirm_real_data": confirm},
                    timeout=20,
                )
                r.raise_for_status()
                st.json(r.json())
            except (httpx.HTTPError, UnicodeError):
                st.error("导入未完成，请检查UTF-8编码、模板、唯一键、外键与金额。")
