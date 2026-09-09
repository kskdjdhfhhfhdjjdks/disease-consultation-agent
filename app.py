"""FastAPI 接口（无状态，兼容 Vercel serverless 与本地 uvicorn）。

会话状态由前端维护并随请求回传，后端不落任何内存状态，可水平扩展/无状态部署。

本地运行：
    uvicorn app:app --host 0.0.0.0 --port 8000
云端：Vercel 自动识别 app.py 导出的 `app`（无需额外配置）

接口：
    GET  /healthz   健康检查（Neo4j / Milvus 连通性）
    POST /api/chat  对话入口 {message, session?} -> {status, reply, report, session}
    GET  /          前端页面（本地开发用）
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

import config
from agent import DiagnosisAgent

app = FastAPI(title="疾病问诊 Agent", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in config.CORS_ORIGINS.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 延迟初始化，避免冷启动时因 Neo4j 暂不可达导致整个模块加载失败
_agent = None


def get_agent() -> DiagnosisAgent:
    global _agent
    if _agent is None:
        _agent = DiagnosisAgent()
    return _agent


class ChatRequest(BaseModel):
    message: str
    session: Optional[dict] = None


@app.get("/healthz")
def healthz():
    checks = {}
    # 用独立 Graph 探测 Neo4j，不依赖 agent 初始化结果
    try:
        from graph import Graph
        g = Graph()
        g.verify()
        checks["neo4j"] = "ok"
        g.close()
    except Exception as e:  # noqa: BLE001
        checks["neo4j"] = f"error: {type(e).__name__}"
    checks["milvus"] = "disabled" if not config.USE_MILVUS else "ok"
    ok = checks["neo4j"].startswith("ok")
    return {"status": "ok" if ok else "degraded", "checks": checks}


@app.post("/api/chat")
def chat(req: ChatRequest):
    session = req.session or {}
    try:
        res = get_agent().diagnose(req.message, session)
    except Exception as e:  # noqa: BLE001 —— 明确报错而不是 500
        return {
            "status": "error",
            "reply": f"后端出错：{type(e).__name__} — {str(e)[:200]}",
            "report": None,
            "symptoms": [],
            "session": session,
            "partial": [],
        }
    return {
        "status": res["status"],
        "reply": res["reply"],
        "report": res.get("report"),
        "symptoms": res.get("symptoms") or list(res["session"]["symptoms"]),
        "session": res["session"],
        "partial": res.get("partial", []),
    }


@app.get("/")
def index():
    return FileResponse("static/index.html")
