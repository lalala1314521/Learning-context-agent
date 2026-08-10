"""/api/v1 报告域路由：学习路径、周报、成就。"""

from fastapi import APIRouter

from app.web.routers.common import ApiError, ok

router = APIRouter()


@router.get("/learning-path")
def learning_path(target: str = ""):
    if not target.strip():
        raise ApiError("需要提供目标概念")
    from app.services.learning_path import build_learning_path, resolve_target
    concept = resolve_target(target.strip())
    if not concept:
        raise ApiError("没有找到匹配的概念", status=404)
    return ok({
        "target": concept,
        "path": build_learning_path(concept["id"]),
    })


@router.get("/weekly-report")
def weekly_report():
    from app.services.weekly_report import generate_weekly_report
    return ok(generate_weekly_report())


@router.get("/achievements")
def achievements():
    from app.services.achievements import get_achievements
    return ok(get_achievements())
