"""/api/v1 复习域路由：测验与复习会话。"""

from fastapi import APIRouter

from app.memory import repository
from app.web.routers.common import ApiError, ok
from app.web.schemas import (
    QuizCreate,
    ReviewSessionAnswer,
    ReviewSessionCreate,
    ReviewSubmit,
)

router = APIRouter()


@router.get("/quiz")
def list_quiz(graph_id: str = ""):
    return ok(repository.list_quiz(graph_id or None))


@router.post("/quiz")
def create_quiz(payload: QuizCreate):
    quiz_id = repository.add_quiz_question(
        payload.graph_id,
        payload.node_id,
        payload.question,
        payload.answer,
        question_type=payload.question_type,
        difficulty=payload.difficulty,
    )
    repository.ensure_review(payload.graph_id, payload.node_id, quiz_id)
    return ok({"id": quiz_id})


@router.get("/review")
def get_review_queue():
    return ok({
        "stats": repository.get_review_stats(),
        "items": repository.get_due_review(limit=20),
    })


@router.get("/review/brief")
def get_daily_brief():
    from app.services.review import daily_brief
    return ok(daily_brief())


@router.post("/review/session")
def create_session(payload: ReviewSessionCreate):
    from app.services.review import create_review_session
    session = create_review_session(
        mode=payload.mode,
        count=payload.count,
        graph_id=payload.graph_id or None,
    )
    return ok(session)


@router.get("/review/session/{session_id}")
def get_review_session(session_id: str):
    from app.services.review import get_session
    session = get_session(session_id)
    if not session:
        raise ApiError("复习会话不存在", status=404)
    return ok(session)


@router.post("/review/session/{session_id}/answer")
def answer_session_item(
    session_id: str,
    payload: ReviewSessionAnswer,
):
    from app.services.review import submit_session_item
    try:
        result = submit_session_item(
            session_id,
            payload.response.get("item_id", ""),
            payload.response,
        )
    except ValueError as exc:
        raise ApiError(str(exc), status=404)
    return ok(result)


@router.post("/review/{review_id}")
def submit_review(review_id: str, payload: ReviewSubmit):
    from app.services.review import submit_review as submit_review_service
    if not submit_review_service(review_id, payload.rating):
        raise ApiError("复习记录不存在", status=404)
    return ok({"id": review_id, "rating": payload.rating})
