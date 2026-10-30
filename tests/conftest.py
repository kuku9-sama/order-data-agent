import pytest

from order_agent.db import generate


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "orders.db"
    generate(p)
    return p
