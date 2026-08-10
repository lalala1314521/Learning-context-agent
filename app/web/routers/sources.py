"""/api/v1 来源域路由：Vault 导入、视频字幕、Anki 导出。"""

from fastapi import APIRouter, Response

from app.web.routers.common import ApiError, ok
from app.web.schemas import VaultImportRequest, VideoSubtitleRequest

router = APIRouter()


@router.post("/sources/import-vault")
def import_vault(payload: VaultImportRequest):
    from app.tools.vault_importer import import_vault as run_import
    try:
        result = run_import(payload.path, limit=payload.limit)
    except ValueError as exc:
        raise ApiError(str(exc))
    return ok(result)


@router.post("/sources/video-subtitle")
def video_subtitle(payload: VideoSubtitleRequest):
    from app.services.chunking import estimate_long_text
    from app.tools.video_subtitles import fetch_video_subtitles
    result = fetch_video_subtitles(payload.url)
    if result.get("error"):
        raise ApiError(result["error"], status=400)
    return ok({
        "source_name": result.get("title") or payload.url,
        "content": result.get("content", ""),
        "preview": estimate_long_text(result.get("content", "")),
    })


@router.get("/export/anki.apkg")
def export_anki():
    from app.services.anki_export import build_apkg_bytes
    try:
        content = build_apkg_bytes()
    except RuntimeError as exc:
        raise ApiError(str(exc), status=501)
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename=learning-context.apkg"},
    )
