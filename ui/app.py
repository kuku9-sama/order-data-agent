import html
import uuid
from decimal import Decimal
from pathlib import Path

import altair as alt
import httpx
import pandas as pd
import streamlit as st

from order_agent.export import export_csv
from order_agent.models import money

st.set_page_config(page_title="订单洞察 · 中文订单分析助手", page_icon="◈", layout="wide")
ROOT = Path(__file__).resolve().parent
st.html("<style>" + (ROOT / "styles.css").read_text() + "</style>")
API = "http://127.0.0.1:8000"
LABELS = {
    "label": "商品 / 分组",
    "sales_cents": "销售额（元）",
    "net_cents": "净额（元）",
    "refund_cents": "退款额（元）",
    "quantity": "销量",
    "name": "商品名称",
    "external_id": "订单号",
    "shop": "店铺",
    "status": "订单状态",
    "paid_at": "支付时间",
    "paid_cents": "实付（元）",
}
for key, default in {
    "session": uuid.uuid4().hex,
    "history": [],
    "result": None,
    "question_value": "",
    "last_question": "",
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


def get_json(path):
    try:
        response = httpx.get(API + path, timeout=3)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError):
        return None


def reset_session():
    st.session_state.session = uuid.uuid4().hex
    st.session_state.history = []
    st.session_state.result = None
    st.session_state.question_value = ""
    st.session_state.last_question = ""
    st.session_state.history_snapshot = False


def select_history(index):
    item = st.session_state.history[index]
    st.session_state.session = uuid.uuid4().hex
    st.session_state.history_snapshot = True
    st.session_state.question_value = item["question"]
    st.session_state.last_question = item["question"]
    st.session_state.result = item["result"]


def ask(question):
    question = question.strip()
    if not question:
        st.warning("请先输入一个订单数据问题。")
        return
    with st.spinner("正在查询订单数据…"):
        try:
            response = httpx.post(
                API + "/chat", json={"question": question, "session_id": st.session_state.session}, timeout=35
            )
            response.raise_for_status()
            result = response.json()
            if result.get("status") not in {"ok", "clarify", "refused"}:
                raise ValueError("响应结构不正确")
            st.session_state.result = result
            st.session_state.history_snapshot = False
            st.session_state.last_question = question
            st.session_state.history = (
                st.session_state.history + [{"question": question, "result": result}]
            )[-8:]
        except (httpx.HTTPError, ValueError):
            st.session_state.result = {
                "status": "error",
                "answer": "查询未完成。请检查API连接或数据状态，然后重试。",
            }
            st.session_state.last_question = question


health = get_json("/health")
overview = get_json("/dataset")
mode = "DeepSeek" if health and health.get("model_mode") == "deepseek" else "本地示例"
with st.sidebar:
    st.html(
        '<div class="brand"><div class="brand-mark">◈</div><div><div class="brand-name">订单洞察</div><div class="brand-sub">ORDER INSIGHT</div></div></div>'
    )
    st.button("＋ 新建会话", key="new_session", on_click=reset_session, width="stretch")
    page = st.radio("工作空间", ["数据问答", "导入数据", "指标口径"], label_visibility="collapsed")
    st.divider()
    st.caption("当前数据集")
    st.markdown("**本地订单数据**")
    st.caption("SQLite · 人民币 · Asia/Shanghai")
    st.caption("查询模式：" + mode if health else "API 未连接，请启动后端服务")
    if overview:
        st.caption(overview["date_start"][:10] + " — " + overview["date_end"][:10])
    if st.session_state.history:
        st.divider()
        st.caption("最近的问题")
        for index in reversed(range(len(st.session_state.history))):
            question = st.session_state.history[index]["question"]
            st.button(
                question[:24],
                key=f"history_{index}",
                on_click=select_history,
                args=(index,),
                width="stretch",
                help=question,
            )
    st.divider()
    st.caption("只读分析 · 导入前备份")

st.html(
    '<div class="workspace-meta"><div class="eyebrow">工作空间 / '
    + html.escape(page)
    + '</div><span class="status-pill">'
    + ("● 数据服务已连接" if overview else "○ 数据服务未就绪")
    + "</span></div>"
)


def render_result(result):
    with st.container(border=True, key="answer_panel"):
        st.subheader("分析结果")
        st.caption(st.session_state.last_question)
        if st.session_state.get("history_snapshot"):
            st.info("正在查看历史结果。继续分析时请提供完整指标，避免沿用其他问题的筛选条件。")
        if result["status"] == "clarify":
            st.warning(result["answer"], icon="💬")
            st.caption("在上方补充指标后继续提问，当前会话会保留必要的筛选条件。")
            return
        if result["status"] in {"refused", "error"}:
            st.error(result["answer"], icon="🔒" if result["status"] == "refused" else "⚠️")
            return
        st.success(result["answer"], icon="✅")
        cols = st.columns(3)
        cols[0].metric("返回记录", f"{len(result['rows'])} 行")
        cols[1].metric("查询用时", f"{result['elapsed_ms']:g} ms")
        cols[2].metric("统计截止", result["cutoff"][:10])
        st.write("")
        df = pd.DataFrame(result["rows"], columns=result["columns"])
        display = df.copy()
        for column in df.columns:
            if column.endswith("_cents"):
                display[column] = display[column].map(
                    lambda value: money(int(value)) if pd.notna(value) else "—"
                )
        display = display.rename(columns=LABELS)
        chart_tab, table_tab, sql_tab = st.tabs(["数据图表", "查询明细", "SQL 与口径"])
        with chart_tab:
            if len(df.columns) == 2 and len(df) and pd.api.types.is_numeric_dtype(df.iloc[:, 1]):
                label, value = df.columns
                chart_df = df.copy()
                if value.endswith("_cents"):
                    # 图表坐标使用元，计算与CSV始终保留整数分。
                    chart_df[value] = chart_df[value].map(lambda cents: float(money(int(cents))))
                is_daily = chart_df[label].astype(str).str.fullmatch(r"\d{4}-\d{2}-\d{2}").all()
                if is_daily:
                    chart = (
                        alt.Chart(chart_df)
                        .mark_line(color="#00856c", point=True)
                        .encode(
                            x=alt.X(f"{label}:O", title="日期", sort="ascending"),
                            y=alt.Y(f"{value}:Q", title=LABELS.get(value, value)),
                            tooltip=list(chart_df.columns),
                        )
                    )
                else:
                    chart = (
                        alt.Chart(chart_df.head(20))
                        .mark_bar(color="#008b76", cornerRadiusEnd=4, size=22)
                        .encode(
                            x=alt.X(f"{value}:Q", title=LABELS.get(value, value)),
                            y=alt.Y(f"{label}:N", title=None, sort="-x"),
                            tooltip=[
                                alt.Tooltip(label, title="分组"),
                                alt.Tooltip(
                                    value,
                                    title=LABELS.get(value, value),
                                    format=",.2f" if value.endswith("_cents") else ",d",
                                ),
                            ],
                        )
                    )
                st.altair_chart(chart.properties(height=330).configure_view(stroke=None), width="stretch")
                st.caption(
                    "按日期排序，缺失日期未补零。"
                    if is_daily
                    else "图表最多展示20个分组；完整返回结果可在「查询明细」查看。"
                )
            elif df.empty:
                st.info("没有符合条件的记录，试试调整时间或店铺。")
            else:
                st.dataframe(display.head(50), hide_index=True, width="stretch")
        with table_tab:
            st.dataframe(display.head(50), hide_index=True, width="stretch")
            st.caption("金额展示单位为元；CSV保留原始字段及整数分。页面最多展示50行。")
        with sql_tab:
            st.code(result["sql"], language="sql")
            st.caption(result["metrics"])
            with st.expander("查看参数与追踪信息"):
                st.json({k: result[k] for k in ["params", "trace_id", "dataset_version", "cutoff"]})
        if result["truncated"]:
            st.warning("结果已截断，请缩小查询范围后重试。")
        st.download_button(
            "↓ 下载查询结果 CSV",
            export_csv(result["columns"], result["rows"]),
            file_name="查询结果.csv",
            mime="text/csv",
            on_click="ignore",
        )


if page == "数据问答":
    st.title("中文订单分析助手")
    st.html('<div class="hero-copy">从订单到洞察，直接提问。销售、退款与每一笔明细，都有据可查。</div>')
    if overview:
        stats = st.columns(4)
        stats[0].metric("订单总数", f"{overview['orders']:,}")
        stats[1].metric("有效销售额", f"¥ {Decimal(overview['sales_cents']) / 100:,.2f}")
        stats[2].metric("成功退款额", f"¥ {Decimal(overview['refund_cents']) / 100:,.2f}")
        stats[3].metric("商品总数", f"{overview['products']:,}")
        st.caption("概览：全部支付期订单；成功退款计入固定统计截止时间之前的记录。")
    else:
        st.info("数据概览暂不可用。请确认API和数据库已就绪。")
    with st.container(border=True, key="query_panel"):
        st.subheader("向数据提问")
        st.caption("用一句话描述你想了解的指标，支持继续修改时间、店铺和排行数量。")
        with st.form("question_form"):
            input_col, submit_col = st.columns([5, 1], vertical_alignment="bottom")
            with input_col:
                question = st.text_input(
                    "输入问题",
                    key="question_value",
                    placeholder="例如：1月销售额最高的前10个商品是哪些？",
                    label_visibility="collapsed",
                )
            with submit_col:
                submit = st.form_submit_button("开始分析 →", type="primary", width="stretch")
        if submit:
            ask(question)
    if st.session_state.result:
        render_result(st.session_state.result)
    else:
        st.write("")
        st.subheader("从一个问题开始")
        suggestions = [
            ("↗", "商品销售排行", "找到销售额靠前的商品", "1月商品销售额前10名"),
            ("↩", "商品退款分析", "按退款完成时间查看排行", "1月退款排行"),
            ("⌁", "每日销售趋势", "看看销售额随日期如何变化", "2月按日销售额前31名"),
            ("▤", "店铺净额对比", "扣除成功退款后的收款净额", "店铺净额前10名"),
        ]
        for col, (icon, title, description, prompt) in zip(st.columns(4), suggestions):
            with col, st.container(border=True, key="suggestion_" + title):
                st.html(
                    f'<div class="suggestion-icon">{icon}</div><div class="suggestion-title">{title}</div><div class="suggestion-description">{description}</div>'
                )
                if st.button("查看分析 ↗", key="suggest_" + title, width="stretch", disabled=not health):
                    ask(prompt)
                    st.rerun()
        st.html(
            '<div class="empty-guide">问题 → 受限 SQL 查询 → 数据与图表<br>所有金额和排名均来自实际查询结果。</div>'
        )
elif page == "导入数据":
    st.title("导入订单数据")
    st.html('<div class="hero-copy">从 CSV 到可查询的数据集。预览校验，确认后再写入。</div>')
    with st.container(border=True, key="import_panel"):
        st.subheader("1. 准备数据文件")
        st.caption("UTF-8 编码 · 金额使用整数分 · 时间包含 +08:00 时区 · 单表不超过2MB、10000行")
        tables = {"products": "商品", "orders": "订单", "order_items": "订单明细", "refunds": "退款"}
        files = {}
        for col, (table, name) in zip(st.columns(4), tables.items()):
            with col:
                st.markdown("**" + name + "**")
                template = ROOT.parent / "data" / "sample" / (table + ".csv")
                st.download_button(
                    "↓ 下载模板",
                    template.read_bytes(),
                    file_name=table + ".csv",
                    mime="text/csv",
                    key="template_" + table,
                )
                files[table] = st.file_uploader(
                    name + " CSV", type=["csv"], key="file_" + table, label_visibility="collapsed"
                )
        st.divider()
        st.subheader("2. 预览校验与导入")
        st.caption("相同记录跳过；冲突与校验错误整批回滚。正式导入前自动备份，本地文件不会发送给模型。")
        confirm = st.checkbox("我确认将所选文件写入本地数据库")
        actions = st.columns([1, 1, 3])
        has_files = any(files.values())
        for column, label, preview in [(actions[0], "预览并校验", True), (actions[1], "确认导入", False)]:
            if column.button(label, disabled=not has_files or (not preview and not confirm), width="stretch"):
                try:
                    payload = {k: v.getvalue().decode("utf-8-sig") for k, v in files.items() if v}
                    response = httpx.post(
                        API + "/imports",
                        json={"files": payload, "preview": preview, "confirm_real_data": confirm},
                        timeout=20,
                    )
                    response.raise_for_status()
                    report = response.json()
                    st.success(
                        ("预览通过，未写入数据库。" if preview else "导入完成，已创建备份。")
                        + f"新增 {report['inserted']} 条，跳过 {report['skipped']} 条。"
                    )
                    with st.expander("查看差异报告"):
                        st.json(report)
                    if not preview:
                        reset_session()
                except (httpx.HTTPError, UnicodeError, KeyError):
                    st.error(
                        "导入未完成。请检查文件编码、模板字段、唯一键、外键及金额；容器只读模式请使用独立导入命令。"
                    )
else:
    st.title("指标口径")
    st.html('<div class="hero-copy">先统一定义，再讨论数字。</div>')
    with st.container(border=True, key="guide_panel"):
        st.markdown("""
|指标|统计方式|
|---|---|
|销售额|支付期内有效明细实付，排除取消订单|
|销量|支付期内有效明细的商品数量|
|退款额|退款完成期内的成功退款|
|净额|支付期销售额减截至统计截止时间的成功退款；不代表利润|
""")
        st.info("时间按 Asia/Shanghai 解释，区间左闭右开。固定统计截止：2025-03-15 零点。")
        st.markdown(
            "**金额与退款**：人民币整数分存储，页面金额展示为元，CSV保留整数分。退款先按明细汇总再关联，避免多次退款重复累计销售额。"
        )
        st.markdown(
            "**查询范围**：单次最多返回200行、页面最多展示50行。大结果请缩小时间或店铺范围。未提供成本、手续费与汇率，不计算利润。"
        )
        st.markdown(
            "**运行模式**：本地示例模式支持有限中文模板，不调用外部模型。启用DeepSeek前需配置凭据并同意向供应商发送问题、必要上下文及数据结构。"
        )
st.html('<div class="footer-note">ORDER INSIGHT · 本地单用户订单分析 · 分析只读，导入独立校验</div>')
