"""/api/v1 图谱域路由：生成、解析、脉络图/节点/链接/分块 CRUD。"""

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile
from starlette.concurrency import run_in_threadpool

from app.config import config
from app.graph.state import build_initial_state
from app.memory import repository
from app.services.graph_management import auto_link, generate_quiz, hydrate_nodes
from app.services.jobs import get_job, start_job
from app.tools.safety import is_internal_url
from app.web.dependencies import ensure_database, get_graph as get_graph_runner
from app.web.routers.common import ApiError, ok
from app.web.schemas import (
    GenerateRequest,
    GraphLinkCreate,
    GraphUpdate,
    NodeCreate,
    NodeUpdate,
)
from app.services.knowledge_contract import canonical_graph_view

router = APIRouter()

MAX_UPLOAD_BYTES = 50 * 1024 * 1024

_STAGE_LABELS = {
    "router": "意图识别",
    "prepare_conversation": "上下文准备",
    "agent": "Agent 思考",
    "tools": "工具执行",
    "parse_content": "内容解析",
    "web_search": "联网搜索",
    "generate_graph": "脉络生成",
    "save_graph": "保存脉络",
    "align_concepts": "概念对齐",
    "persist_graph_memory": "记忆持久化",
    "list_graphs": "列出脉络",
    "search_graphs": "检索脉络",
    "get_graph": "打开脉络",
    "manage_graph": "管理节点",
}


def _stage_label(node_name: str) -> str:
    return _STAGE_LABELS.get(node_name, node_name or "处理中")


def _validate_upload(filename: str, raw: bytes) -> str | None:
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".pdf" and not raw.startswith(b"%PDF-"):
        return "文件内容不是有效的 PDF"
    if suffix == ".docx" and not raw.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        return "文件内容不是有效的 DOCX"
    if suffix in (".txt", ".md", ".ipynb", ".py", ".html", ".json"):
        if b"\x00" in raw:
            return "文本文件包含二进制内容"
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            return "文本文件必须使用 UTF-8 编码"
        if suffix == ".ipynb":
            try:
                json.loads(raw.decode("utf-8"))
            except Exception:
                return "IPYNB 文件 JSON 解析失败"
    return None


def _summarize_graph(row: dict) -> dict:
    keys = (
        "id", "title", "description", "graph_type",
        "source_type", "source_name", "tags", "created_at", "updated_at",
    )
    return {key: row.get(key) for key in keys}


def _concept_links_for_nodes(nodes: list[dict]) -> list[dict]:
    concept_ids = {
        node.get("concept_id")
        for node in nodes
        if node.get("concept_id")
    }
    if not concept_ids:
        return []
    links = repository.list_concept_links(limit=10000, min_confidence=0.0)
    return [
        link for link in links
        if link["from_concept"] in concept_ids and link["to_concept"] in concept_ids
    ]


@router.get("/health")
def health():
    ensure_database()
    return ok({"status": "healthy"})


@router.post("/graphs/generate")
def generate_graph(payload: GenerateRequest):
    thread_id = payload.thread_id or f"web-{uuid.uuid4().hex}"
    try:
        result = get_graph_runner().invoke(
            build_initial_state(
                payload.content,
                output_format=payload.output_format,
                web_search_enabled=payload.web_search_enabled,
            ),
            {"configurable": {"thread_id": thread_id}},
        )
    except Exception as e:
        raise ApiError(f"脉络生成失败: {e}", status=502)
    if result.get("error"):
        raise ApiError(result["error"], status=502)
    graph_id = result.get("current_graph_id", "")
    graph = repository.get_graph(graph_id) if graph_id else None
    nodes = repository.get_nodes(graph_id) if graph_id else []
    auto_links = []
    if payload.auto_link and graph_id:
        auto_links = auto_link(graph_id, nodes)
    if graph_id:
        generate_quiz(graph_id, nodes)
    return ok({
        "id": graph_id,
        "title": graph.get("title") if graph else None,
        "graph_type": graph.get("graph_type") if graph else None,
        "mermaid": result.get("graph_mermaid", ""),
        "markdown": result.get("graph_markdown", ""),
        "memory_snapshot_id": result.get("memory_snapshot_id", ""),
        "concept_report": result.get("concept_report") or {},
        "concepts": repository.get_concepts_for_graph(graph_id) if graph_id else [],
        "concept_links": _concept_links_for_nodes(nodes) if graph_id else [],
        "long_text_report": result.get("long_text_report") or {},
        "long_text_chapter_graph_ids": result.get("long_text_chapter_graph_ids") or [],
        "chunk_count": len(repository.list_content_chunks(graph_id)) if graph_id else 0,
        "nodes": nodes,
        "auto_links": auto_links,
    })


@router.post("/graphs/generate/async")
def generate_graph_async(payload: GenerateRequest):
    """Start generation in a background job and return a pollable job id.

    使用 graph.stream 逐节点产出，实时把 Agent 轨迹（思考/工具调用/观察/后处理）
    写入 job.trace，供前端轮询实时展示。
    """

    def runner(job: dict | None = None) -> dict:
        import time

        from app.graph.trace import build_trace_events

        thread_id = payload.thread_id or f"web-{uuid.uuid4().hex}"
        graph = get_graph_runner()
        initial = build_initial_state(
            payload.content,
            output_format=payload.output_format,
            web_search_enabled=payload.web_search_enabled,
            selected_chapters=payload.selected_chapters,
        )
        config_ctx = {"configurable": {"thread_id": thread_id}}

        started = time.time()
        trace: list[dict] = list((job or {}).get("trace") or [])
        total_tokens = 0
        final: dict = {}
        try:
            for chunk in graph.stream(initial, config_ctx):
                for node_name, update in chunk.items():
                    final.update(update)
                    for event in build_trace_events(node_name, update):
                        event["ms"] = int((time.time() - started) * 1000)
                        total_tokens += int(event.get("tokens") or 0)
                        trace.append(event)
                    if job is not None:
                        job["trace"] = list(trace)
                        job["total_tokens"] = total_tokens
                        job["elapsed_ms"] = int((time.time() - started) * 1000)
                        job["stage"] = _stage_label(node_name)
                        job["progress"] = min(90, 5 + len(trace) * 9)
        except Exception as exc:
            raise ApiError(f"脉络生成失败: {exc}", status=502)

        if final.get("error"):
            raise ApiError(final["error"], status=502)
        graph_id = final.get("current_graph_id", "")
        graph = repository.get_graph(graph_id) if graph_id else None
        nodes = repository.get_nodes(graph_id) if graph_id else []
        auto_links = []
        if payload.auto_link and graph_id:
            auto_links = auto_link(graph_id, nodes)
        if graph_id:
            generate_quiz(graph_id, nodes)
        return {
            "id": graph_id,
            "title": graph.get("title") if graph else None,
            "graph_type": graph.get("graph_type") if graph else None,
            "mermaid": final.get("graph_mermaid", ""),
            "markdown": final.get("graph_markdown", ""),
            "memory_snapshot_id": final.get("memory_snapshot_id", ""),
            "concept_report": final.get("concept_report") or {},
            "concepts": repository.get_concepts_for_graph(graph_id) if graph_id else [],
            "concept_links": _concept_links_for_nodes(nodes) if graph_id else [],
            "long_text_report": final.get("long_text_report") or {},
            "long_text_chapter_graph_ids": final.get("long_text_chapter_graph_ids") or [],
            "chunk_count": len(repository.list_content_chunks(graph_id)) if graph_id else 0,
            "nodes": nodes,
            "auto_links": auto_links,
            "trace": trace,
            "total_tokens": total_tokens,
        }

    job_id = start_job(runner, title=payload.content[:40])
    return ok({"id": job_id})


@router.get("/jobs/{job_id}")
def get_generation_job(job_id: str):
    job = get_job(job_id)
    if not job:
        raise ApiError("任务不存在", status=404)
    return ok(job)


@router.post("/graphs/parse")
async def parse_source(
    file: UploadFile | None = File(default=None),
    url: str | None = Form(default=None),
    text: str | None = Form(default=None),
):
    ensure_database()
    if file is not None:
        raw = await file.read()
        if len(raw) > MAX_UPLOAD_BYTES:
            raise ApiError("文件超过 50MB 限制")
        suffix = Path(file.filename or "").suffix.lower()
        if not suffix:
            raise ApiError("无法识别文件类型")
        invalid = _validate_upload(file.filename or "", raw)
        if invalid:
            raise ApiError(invalid)
        target = Path(config.DATABASE_PATH).parent / "uploads"
        target.mkdir(parents=True, exist_ok=True)
        temp_path = target / f"{uuid.uuid4().hex}{suffix}"
        try:
            temp_path.write_bytes(raw)

            def _parse_temp() -> dict:
                from app.tools.doc_parser import parse_document
                return parse_document(str(temp_path))

            parsed = await run_in_threadpool(_parse_temp)
        finally:
            temp_path.unlink(missing_ok=True)
        if parsed.get("error"):
            raise ApiError(parsed["error"])

        def _preview() -> dict:
            from app.services.chunking import estimate_long_text
            return estimate_long_text(parsed["content"])

        return ok({
            "source_name": parsed.get("title") or (file.filename or ""),
            "content": parsed["content"],
            "preview": await run_in_threadpool(_preview),
        })
    if url:
        if is_internal_url(url):
            raise ApiError("不允许访问内网地址")

        def _fetch() -> dict:
            from app.tools.web_fetcher import fetch_url
            return fetch_url(url)

        parsed = await run_in_threadpool(_fetch)
        if parsed.get("error"):
            raise ApiError(parsed["error"])

        def _preview2() -> dict:
            from app.services.chunking import estimate_long_text
            return estimate_long_text(parsed["content"])

        return ok({
            "source_name": parsed.get("url") or url,
            "content": parsed["content"],
            "preview": await run_in_threadpool(_preview2),
        })
    if text is not None:
        from app.services.chunking import estimate_long_text
        return ok({
            "source_name": "",
            "content": text,
            "preview": estimate_long_text(text),
        })
    raise ApiError("需要提供 file、url 或 text 之一")


@router.get("/graphs")
def list_graphs(q: str = ""):
    ensure_database()
    rows = (
        repository.search_graphs(q.strip(), limit=50)
        if q.strip()
        else repository.list_graphs(limit=50)
    )
    return ok([_summarize_graph(row) for row in rows])


@router.get("/graphs/{graph_id}")
def get_graph(graph_id: str):
    graph = repository.get_graph(graph_id)
    if not graph:
        raise ApiError("脉络图不存在", status=404)
    hydrate_nodes(graph_id)
    nodes = repository.get_nodes(graph_id)
    links = repository.list_links(graph_id)
    return ok({
        "graph": graph,
        "nodes": nodes,
        "concept_links": _concept_links_for_nodes(nodes),
        "links": links,
        "structure": canonical_graph_view(graph, nodes, links),
    })


@router.get("/graphs/{graph_id}/outline")
def get_outline(graph_id: str):
    if not repository.get_graph(graph_id):
        raise ApiError("脉络图不存在", status=404)
    hydrate_nodes(graph_id)
    return ok(repository.get_outline(graph_id))


@router.delete("/graphs/{graph_id}")
def delete_graph(graph_id: str):
    repository.delete_graph(graph_id)
    return ok({"id": graph_id})


@router.patch("/graphs/{graph_id}")
def update_graph(graph_id: str, payload: GraphUpdate):
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise ApiError("没有可更新的字段")
    return ok({"ok": repository.update_graph(graph_id, **updates)})


@router.post("/nodes")
def create_node(payload: NodeCreate):
    node_id = repository.add_node(
        payload.graph_id,
        payload.label,
        parent_id=payload.parent_id,
        note=payload.note,
        node_type=payload.node_type,
        related_nodes=payload.related_nodes,
        order_index=payload.order_index,
        created_by="user",
    )
    return ok({"id": node_id})


@router.patch("/nodes/{node_id}")
def update_node(node_id: str, payload: NodeUpdate):
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise ApiError("没有可更新的字段")
    return ok({"ok": repository.update_node(node_id, **updates)})


@router.delete("/nodes/{node_id}")
def delete_node(node_id: str):
    repository.delete_node(node_id)
    return ok({"id": node_id})


@router.get("/memories")
def list_memories(limit: int = 50):
    ensure_database()
    return ok(repository.get_memory_snapshots(limit=min(limit, 100)))


@router.get("/chunks")
def list_chunks(graph_id: str = "", limit: int = 500):
    ensure_database()
    if not graph_id:
        return ok([])
    return ok(repository.list_content_chunks(graph_id, limit=min(limit, 1000)))


@router.get("/links")
def list_links(graph_id: str = ""):
    return ok(repository.list_links(graph_id or None))


@router.post("/links")
def create_link(payload: GraphLinkCreate):
    link_id = repository.create_link(
        payload.from_graph_id,
        payload.from_node_id,
        payload.to_graph_id,
        payload.to_node_id,
        relation_type=payload.relation_type,
        note=payload.note,
    )
    return ok({"id": link_id})


@router.delete("/links/{link_id}")
def delete_link(link_id: str):
    repository.delete_link(link_id)
    return ok({"id": link_id})


@router.post("/graphs/{graph_id}/quiz/generate")
def generate_quiz_for_graph(graph_id: str):
    if not repository.get_graph(graph_id):
        raise ApiError("脉络图不存在", status=404)
    count = generate_quiz(graph_id, repository.get_nodes(graph_id))
    return ok({"generated": count})
