"""FastAPI 接口（无状态，兼容 Vercel serverless 与本地 uvicorn）。

会话状态由前端维护并随请求回传，后端不落任何内存状态，可水平扩展/无状态部署。

本地运行：
    uvicorn app:app --host 0.0.0.0 --port 8000
云端：Vercel 自动识别 app.py 导出的 `app`（无需额外配置）

接口：
    GET  /healthz   健康检查（Neo4j / Milvus）
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

# 允许 Netlify 前端跨域访问（来源用 config.CORS_ORIGINS 配置，默认 *）
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in config.CORS_ORIGINS.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

agent = DiagnosisAgent()


class ChatRequest(BaseModel):
    message: str
    session: Optional[dict] = None


@app.get("/healthz")
def healthz():
    checks = {}
    try:
        agent.graph.verify()
        checks["neo4j"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["neo4j"] = f"error: {type(e).__name__}"
    checks["milvus"] = "disabled" if not config.USE_MILVUS else "ok"
    ok = checks["neo4j"].startswith("ok")
    return {"status": "ok" if ok else "degraded", "checks": checks}


@app.post("/api/chat")
def chat(req: ChatRequest):
    session = req.session or {}
    res = agent.diagnose(req.message, session)
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
