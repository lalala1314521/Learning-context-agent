"""API 路由聚合：按业务域拆分的子路由合并为一个 APIRouter。"""

from fastapi import APIRouter

from app.web.routers.common import ApiError, ok  # noqa: F401
from app.web.routers.concepts import router as concepts_router
from app.web.routers.graphs import router as graphs_router
from app.web.routers.knowledge import router as knowledge_router
from app.web.routers.reports import router as reports_router
from app.web.routers.review import router as review_router
from app.web.routers.sources import router as sources_router

router = APIRouter()
router.include_router(graphs_router)
router.include_router(concepts_router)
router.include_router(review_router)
router.include_router(sources_router)
router.include_router(knowledge_router)
router.include_router(reports_router)
