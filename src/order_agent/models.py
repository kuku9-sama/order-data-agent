from decimal import Decimal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    session_id: str = Field(default="default", max_length=100)


class ImportRequest(BaseModel):
    files: dict[str, str]
    preview: bool = True
    confirm_real_data: bool = False


def money(cents):
    return str((Decimal(cents) / Decimal(100)).quantize(Decimal("0.01")))
