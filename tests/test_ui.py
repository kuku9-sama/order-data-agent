from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_page():
    page = AppTest.from_file(Path(__file__).resolve().parents[1] / "ui/app.py").run(timeout=20)
    assert not page.exception
    assert page.title[0].value == "中文订单分析助手"
    assert len(page.text_input) == 1
