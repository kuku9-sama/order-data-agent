import os
import sqlite3
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .agent import Agent
from .config import DB_PATH
from .imports import import_csv
from .models import ChatRequest, ImportRequest
from .tools import structure

app = FastAPI(title="中文订单分析助手", version="0.1.0")
from .provider import DeepSeekAgent

agent = DeepSeekAgent(DB_PATH) if os.getenv("ORDER_MODEL_MODE") == "deepseek" else Agent(DB_PATH)


@app.exception_handler(Exception)
async def error(request: Request, exc: Exception):
    return JSONResponse(
        status_code=400,
        content={
            "status": "error",
            "error": "请求未完成，请检查数据、SQL权限或资源限制。",
            "trace_id": uuid4().hex,
        },
    )


@app.get("/health")
def health():
    return {"status": "ok", "model_mode": os.getenv("ORDER_MODEL_MODE", "offline")}


@app.get("/ready")
def ready():
    if len(structure(agent.path)) != 4:
        raise ValueError("数据库结构不完整")
    with sqlite3.connect(agent.path) as con:
        if con.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
            raise ValueError("无商品数据")
    return {"status": "ready", "model_mode": os.getenv("ORDER_MODEL_MODE", "offline")}


@app.post("/chat")
def chat(body: ChatRequest):
    return agent.chat(body.question, body.session_id)


@app.post("/imports")
def imports(body: ImportRequest):
    if os.getenv("ORDER_IMPORT_DISABLED") == "yes":
        raise ValueError("当前API只读，请使用独立导入命令")
    if not body.preview and not body.confirm_real_data:
        raise ValueError("请明确确认导入到本地数据库")
    with agent.lock:
        result = import_csv(agent.path, body.files, body.preview)
        if not body.preview:
            agent.sessions.clear()
            if hasattr(agent, "dataset_version"):
                agent.dataset_version = "local-imported"
        return result


@app.post("/model/test")
def model_test():
    return {"status": "unconfigured", "message": "当前仅离线替身；无外部模型调用或费用。"}
