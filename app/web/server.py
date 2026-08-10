"""FastAPI 应用与启动入口。"""

import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.logging_config import setup_logging
from app.web.api import ApiError, router

setup_logging()
BASE_DIR = Path(__file__).resolve().parent


class NoCacheStaticFiles(StaticFiles):
    """静态资源禁用浏览器缓存，保证前端模块每次拉取最新版本。"""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response


def create_app() -> FastAPI:
    app = FastAPI(
        title="学习脉络智能体 WebUI",
        version="0.1.0",
        description="本地学习脉络可视化与管理界面",
    )

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError):
        return JSONResponse(
            status_code=exc.status,
            content={"ok": False, "data": None, "error": exc.message},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "ok": False,
                "data": None,
                "error": "请求参数不合法",
                "detail": exc.errors(),
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={"ok": False, "data": None, "error": str(exc)},
        )

    app.include_router(router, prefix="/api/v1")
    app.mount(
        "/static",
        NoCacheStaticFiles(directory=BASE_DIR / "static"),
        name="static",
    )

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(
            BASE_DIR / "templates" / "index.html",
            headers={"Cache-Control": "no-cache"},
        )

    return app


app = create_app()


def main() -> None:
    import uvicorn

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    uvicorn.run("app.web.server:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    main()
