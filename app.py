"""FastAPI 接口 + 前端托管。

运行：
    uvicorn app:app --host 0.0.0.0 --port 8000
然后浏览器打开 http://127.0.0.1:8000

接口：
    GET  /                    前端页面
    POST /api/chat            对话主入口 {message, session_id?}
    POST /api/reset           重置会话 {session_id?}
    GET  /api/report/{id}     取某会话的诊断报告
    GET  /healthz             健康检查（Neo4j / Milvus）
"""
import uuid

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

import config
from agent import DiagnosisAgent

app = FastAPI(title="疾病问诊 Agent", version="1.0")

# 允许 Netlify 前端跨域访问（来源用 config.CORS_ORIGINS 配置）
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in config.CORS_ORIGINS.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

agent = DiagnosisAgent()
_sessions: dict = {}   # session_id -> 会话状态（含已收集症状/追问计数）
_reports: dict = {}    # session_id -> 最近一次结构化报告


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


@app.get("/healthz")
def healthz():
    checks = {}
    try:
        agent.graph.verify()
        checks["neo4j"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["neo4j"] = f"error: {type(e).__name__}"
    try:
        from pymilvus import utility
        n = len(utility.list_collections())
        checks["milvus"] = f"ok ({n} collections)"
    except Exception as e:  # noqa: BLE001
        checks["milvus"] = f"error: {type(e).__name__}"
    ok = all(v.startswith("ok") for v in checks.values())
    return {"status": "ok" if ok else "degraded", "checks": checks}


@app.post("/api/chat")
def chat(req: ChatRequest):
    sid = req.session_id or uuid.uuid4().hex
    session = _sessions.get(sid)
    res = agent.diagnose(req.message, session)
    _sessions[sid] = res["session"]
    if res["status"] == "done":
        _reports[sid] = res["report"]
    return {
        "session_id": sid,
        "status": res["status"],
        "reply": res["reply"],
        "report": res.get("report"),
        "symptoms": res.get("symptoms") or list(res["session"]["symptoms"]),
        "partial": res.get("partial", []),
    }


@app.post("/api/reset")
def reset(req: ChatRequest):
    if req.session_id:
        _sessions.pop(req.session_id, None)
        _reports.pop(req.session_id, None)
    return {"status": "reset", "session_id": req.session_id}


@app.get("/api/report/{session_id}")
def get_report(session_id: str):
    return {"session_id": session_id, "report": _reports.get(session_id)}


# 前端静态资源
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    return FileResponse("static/index.html")
