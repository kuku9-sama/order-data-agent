import json

import httpx
import pytest

from order_agent.provider import DeepSeekAgent


def message(calls=None, content=None):
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"role": "assistant", "content": content, "tool_calls": calls}}],
            "usage": {"total_tokens": 10},
        },
    )


def call(name, args=None):
    return {"id": name, "type": "function", "function": {"name": name, "arguments": json.dumps(args or {})}}


def agent(db, monkeypatch, handler):
    monkeypatch.setenv("ORDER_ALLOW_EXTERNAL", "yes")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    return DeepSeekAgent(db, transport=httpx.MockTransport(handler))


def test_tools_success(db, monkeypatch):
    seq = iter(
        [
            message([call("schema"), call("metrics")]),
            message([call("query", {"sql": "SELECT COUNT(*) AS quantity FROM orders", "params": {}})]),
        ]
    )
    a = agent(db, monkeypatch, lambda r: next(seq))
    result = a.chat("订单数量", "x")
    assert result["rows"] == [(1000,)] and result["tool_calls"] == 3
    assert result["usage"] == [{"total_tokens": 10}] * 2


@pytest.mark.parametrize("kind", ["timeout", "rate", "invalid", "loop", "denied"])
def test_termination(db, monkeypatch, kind):
    def handle(request):
        if kind == "timeout":
            raise httpx.ReadTimeout("timeout")
        if kind == "rate":
            return httpx.Response(429)
        if kind == "invalid":
            return message(content="not-json")
        if kind == "denied":
            return message([call("query", {"sql": "DROP TABLE orders", "params": {}})])
        return message([call("schema")])

    a = agent(db, monkeypatch, handle)
    with pytest.raises((httpx.HTTPError, ValueError, TimeoutError)):
        a.chat("问题", "x")
    assert a.calls <= 8


def test_sql_correction(db, monkeypatch):
    seq = iter(
        [
            message([call("schema"), call("metrics")]),
            message([call("query", {"sql": "SELECT missing FROM orders", "params": {}})]),
            message([call("query", {"sql": "SELECT COUNT(*) FROM orders", "params": {}})]),
        ]
    )
    a = agent(db, monkeypatch, lambda r: next(seq))
    assert a.chat("订单数量", "x")["rows"] == [(1000,)]


def test_no_consent(db, monkeypatch):
    monkeypatch.delenv("ORDER_ALLOW_EXTERNAL", raising=False)
    a = DeepSeekAgent(db)
    with pytest.raises(ValueError):
        a.chat("订单数量", "x")
    assert a.calls == 0
