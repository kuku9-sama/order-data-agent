from pathlib import Path

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from order_agent.agent import Agent


@pytest.fixture
def page(db, monkeypatch):
    agent = Agent(db)

    def get(url, **kwargs):
        data = {"status": "ok", "model_mode": "offline"}
        if url.endswith("/dataset"):
            data = {
                "orders": 1000,
                "sales_cents": 1000000,
                "refund_cents": 10000,
                "products": 100,
                "date_start": "2025-01-01",
                "date_end": "2025-02-28",
            }
        return httpx.Response(200, json=data, request=httpx.Request("GET", url))

    def post(url, json, **kwargs):
        result = agent.chat(json["question"], json["session_id"])
        return httpx.Response(200, json=result, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(httpx, "post", post)
    return AppTest.from_file(Path(__file__).resolve().parents[1] / "ui/app.py").run(timeout=20)


def test_page(page):
    assert not page.exception
    assert page.title[0].value == "中文订单分析助手"
    assert len(page.text_input) == 1
    assert len(page.metric) == 4


def test_suggestion_result_survives_navigation(page):
    page.button(key="suggest_商品销售排行").click().run()
    assert not page.exception
    assert len(page.session_state["result"]["rows"]) == 10
    page.radio[0].set_value("指标口径").run()
    assert page.title[0].value == "指标口径"
    page.radio[0].set_value("数据问答").run()
    assert page.session_state["result"]["status"] == "ok"
    assert len(page.tabs) == 3
    page.button(key="new_session").click().run()
    assert page.session_state["result"] is None
    assert page.session_state["history"] == []


def test_question_and_history(page):
    page.text_input[0].set_value("1月销售额前3名")
    next(b for b in page.button if b.label == "开始分析 →").click().run()
    assert not page.exception
    assert len(page.session_state["result"]["rows"]) == 3
    page.text_input[0].set_value("改成2月前5名")
    next(b for b in page.button if b.label == "开始分析 →").click().run()
    assert len(page.session_state["result"]["rows"]) == 5
    page.button(key="history_0").click().run()
    assert page.session_state["last_question"] == "1月销售额前3名"
    assert len(page.session_state["result"]["rows"]) == 3
    page.text_input[0].set_value("改成2月前5名")
    next(b for b in page.button if b.label == "开始分析 →").click().run()
    assert page.session_state["result"]["status"] == "clarify"


def test_import_requires_files_and_confirmation(page):
    page.radio[0].set_value("导入数据").run()
    assert not page.exception
    assert page.title[0].value == "导入订单数据"
    assert next(b for b in page.button if b.label == "预览并校验").disabled
    assert next(b for b in page.button if b.label == "确认导入").disabled
