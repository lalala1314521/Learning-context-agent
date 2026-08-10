"""/api/v1 知识问答域路由。"""

import time

from fastapi import APIRouter

from app.services.jobs import start_job
from app.services.knowledge import answer_question
from app.web.dependencies import ensure_database
from app.web.routers.common import ApiError, ok
from app.web.schemas import AskRequest

router = APIRouter()


@router.post("/ask")
def ask_knowledge(payload: AskRequest):
    ensure_database()
    try:
        result = answer_question(
            payload.question,
            use_database=payload.use_database,
        )
    except Exception as e:
        raise ApiError(f"知识问答失败: {e}", status=502)
    return ok({
        "question": payload.question,
        "answer": result["answer"],
        "sources": result["sources"],
        "has_sources": result["has_sources"],
        "web_fallback_used": result["web_fallback_used"],
    })


@router.post("/ask/async")
def ask_knowledge_async(payload: AskRequest):
    """异步知识问答：实时返回 Agent 思考链/检索/联网/回答轨迹（复用生成轨迹面板）。"""

    def runner(job: dict | None = None) -> dict:
        started = time.time()
        trace: list[dict] = []

        def on_event(event: dict) -> None:
            event["ms"] = int((time.time() - started) * 1000)
            trace.append(event)
            if job is not None:
                job["trace"] = list(trace)
                job["total_tokens"] = sum(int(e.get("tokens") or 0) for e in trace)
                job["elapsed_ms"] = int((time.time() - started) * 1000)
                job["stage"] = "知识问答"
                job["progress"] = min(90, 10 + len(trace) * 20)

        result = answer_question(
            payload.question,
            use_database=payload.use_database,
            on_event=on_event,
        )
        result["trace"] = trace
        result["total_tokens"] = sum(int(e.get("tokens") or 0) for e in trace)
        return result

    job_id = start_job(runner, title=payload.question[:40])
    return ok({"id": job_id})
