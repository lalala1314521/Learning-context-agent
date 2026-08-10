"""/api/v1 知识问答域路由。"""

from fastapi import APIRouter

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
