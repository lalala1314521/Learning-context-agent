"""/api/v1 知识问答域路由。"""

from fastapi import APIRouter

from app.services.knowledge import ask_llm, build_knowledge_context
from app.web.dependencies import ensure_database
from app.web.routers.common import ApiError, ok
from app.web.schemas import AskRequest

router = APIRouter()


@router.post("/ask")
def ask_knowledge(payload: AskRequest):
    ensure_database()
    context, sources = build_knowledge_context(payload.question)
    if not payload.use_database:
        context = ""
        sources = []
    try:
        answer = ask_llm(payload.question, context)
    except Exception as e:
        raise ApiError(f"知识问答失败: {e}", status=502)
    return ok({
        "question": payload.question,
        "answer": answer,
        "sources": sources,
        "has_sources": bool(sources),
    })
