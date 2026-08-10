"""/api/v1 路由聚合入口（向后兼容再导出）。

路由已按业务域拆分到 app/web/routers/，此处仅聚合，供 server.py 与旧测试引用。
"""

from app.web.routers import ApiError, ok, router  # noqa: F401
