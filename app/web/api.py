"""/api/v1 路由：脉络、节点、记忆与内容解析。"""

import ipaddress
import json
import re
import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, File, Form, Response, UploadFile

from app.config import config
from app.graph.mermaid_parser import parse_graph_structure
from app.memory import repository
from app.web.dependencies import ensure_database, get_graph as get_graph_runner
from app.web.schemas import (
    AskRequest,
    GenerateRequest,
    GraphLinkCreate,
    GraphUpdate,
    ConceptLinkStatusUpdate,
    ConceptMergeRequest,
    VaultImportRequest,
    VideoSubtitleRequest,
    NodeCreate,
    NodeUpdate,
    QuizCreate,
    ReviewSessionAnswer,
    ReviewSessionCreate,
    ReviewSubmit,
)
from app.services.jobs import get_job, start_job

router = APIRouter()

MAX_UPLOAD_BYTES = 50 * 1024 * 1024


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def ok(data):
    return {"ok": True, "data": data, "error": None}


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


def _is_internal_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return True
    if host.endswith(".local") or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        return False


def _summarize_graph(row: dict) -> dict:
    keys = (
        "id", "title", "description", "graph_type",
        "source_type", "source_name", "tags", "created_at", "updated_at",
    )
    return {key: row.get(key) for key in keys}


_QUESTION_NOISE = re.compile(
    r"(什么是|怎么|如何|为什么|吗|呢|请|解释|介绍|有哪些|什么|介绍一下|"
    r"的区别|的用途|的原理|好不好|行不行)",
)


def _knowledge_query(question: str) -> str:
    cleaned = _QUESTION_NOISE.sub(" ", question)
    cleaned = re.sub(r"[^\w]+", "", cleaned, flags=re.UNICODE).strip()
    return cleaned or question


def _hydrate_nodes(graph_id: str) -> int:
    """旧图缺少节点时，从 Mermaid / Markdown 补解析节点落库。"""
    graph = repository.get_graph(graph_id)
    if not graph or repository.get_nodes(graph_id):
        return 0
    nodes = parse_graph_structure(
        graph.get("mermaid_code") or "",
        graph.get("markdown_outline") or "",
    )
    for index, node in enumerate(nodes):
        repository.add_node(
            graph_id,
            label=node["label"],
            parent_id=node["parent_id"],
            related_nodes=node["related_nodes"],
            order_index=node["order_index"],
            created_by="agent",
            node_id=node["id"],
            note=node.get("note") or "",
        )
    return len(nodes)


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


def _initial_state(
    content: str,
    output_format: str,
    web_search: bool,
    selected_chapters: list[int] | None = None,
) -> dict:
    fmt = "both" if output_format in ("auto", "both") else output_format
    return {
        "messages": [],
        "user_input": content,
        "input_type": "text",
        "parsed_content": "",
        "source_name": "",
        "output_format": fmt,
        "web_search_enabled": web_search,
        "supplementary_info": "",
        "current_graph_id": "",
        "graph_mermaid": "",
        "graph_markdown": "",
        "node_payloads": "",
        "memory_snapshot_id": "",
        "concept_report": {},
        "long_text_report": {},
        "long_text_tier": "",
        "long_text_chunks": [],
        "chapter_payloads": [],
        "long_text_chapter_graph_ids": [],
        "selected_chapters": selected_chapters or [],
        "action": "",
        "error": "",
    }


def _char_overlap(a: str, b: str) -> float:
    if not a or not b:
        return 0
    sa, sb = set(a.lower()), set(b.lower())
    return len(sa & sb) / max(len(sa), len(sb))


def _auto_link(graph_id: str, nodes: list[dict]) -> list[dict]:
    """按节点文本相似度自动建立跨脉络链接。"""
    if not nodes:
        return []
    existing = [g for g in repository.list_graphs(limit=100) if g["id"] != graph_id]
    created: list[dict] = []
    existing_links = repository.list_links(graph_id)
    seen = {
        (link["from_node_id"], link["to_graph_id"], link["to_node_id"])
        for link in existing_links
    }
    for graph in existing:
        targets = repository.get_nodes(graph["id"])
        for node in nodes:
            for target in targets:
                if _char_overlap(node["label"], target["label"]) >= 0.5:
                    key = (node["id"], graph["id"], target["id"])
                    if key in seen:
                        continue
                    link_id = repository.create_link(
                        graph_id,
                        node["id"],
                        graph["id"],
                        target["id"],
                        relation_type="related",
                    )
                    seen.add(key)
                    created.append({
                        "link_id": link_id,
                        "from_node_id": node["id"],
                        "from_node_label": node["label"],
                        "to_graph_id": graph["id"],
                        "to_graph_title": graph["title"],
                        "to_node_id": target["id"],
                        "to_node_label": target["label"],
                    })
    return created[:20]


def _generate_quiz(graph_id: str, nodes: list[dict]) -> int:
    """为没有题目的节点生成基础回忆题与复习进度。"""
    existing = {q["node_id"] for q in repository.list_quiz(graph_id)}
    count = 0
    for node in nodes:
        if node["id"] in existing:
            continue
        answer = node.get("note") or f"请回顾：{node['label']}"
        quiz_id = repository.add_quiz_question(
            graph_id,
            node["id"],
            f"什么是「{node['label']}」？",
            answer,
            question_type="short_answer",
        )
        repository.ensure_review(graph_id, node["id"], quiz_id)
        count += 1
    return count


def _build_knowledge_context(query: str) -> tuple[str, list[dict]]:
    query = _knowledge_query(query)
    sources: list[dict] = []
    parts: list[str] = []
    for graph in repository.search_graphs(query, limit=5):
        sources.append({"type": "graph", "id": graph["id"], "title": graph["title"]})
        raw = (graph.get("raw_content") or "")[:600]
        if raw.strip():
            parts.append(f"[脉络 {graph['title']}]\n{raw}")
    for node in repository.search_nodes(query, limit=10):
        sources.append({
            "type": "node",
            "id": node["id"],
            "graph_id": node["graph_id"],
            "graph_title": node.get("graph_title") or "",
            "label": node["label"],
        })
        note = (node.get("note") or "")[:400]
        if note.strip():
            parts.append(f"[节点 {node['label']}]\n{note}")
    for memory in repository.search_memories(query, limit=5):
        sources.append({
            "type": "memory",
            "id": memory["id"],
            "summary": memory["summary"],
        })
        parts.append(f"[记忆摘要]\n{memory['summary']}")
    for chunk in repository.search_content_chunks(query, limit=5):
        sources.append({
            "type": "chunk",
            "id": chunk["id"],
            "graph_id": chunk["graph_id"],
            "graph_title": chunk.get("graph_title") or "",
            "chunk_index": chunk.get("chunk_index"),
            "text": (chunk.get("text") or "")[:200],
        })
        snippet = (chunk.get("text") or "")[:600]
        if snippet.strip():
            parts.append(
                f"[原文分块 · {chunk.get('graph_title') or chunk['graph_id']} "
                f"#{chunk.get('chunk_index')}]\n{snippet}"
            )
    return "\n\n".join(parts)[:8000], sources


def _local_answer(question: str, context: str) -> str:
    if not context.strip():
        return (
            "知识库未直接覆盖该问题。建议先补充相关材料，"
            "或换一个更接近已有脉络的关键词检索。"
        )
    return (
        "已收录知识（本地检索结果）：\n\n"
        f"{context[:1600]}\n\n"
        "（当前 DeepSeek 暂不可用，以上为知识库原文片段；"
        "可稍后重试获得更完整的回答。）"
    )


def _ask_llm(question: str, context: str):
    from langchain_core.messages import HumanMessage, SystemMessage
    from app.graph.nodes import _get_llm

    system = (
        "你是学习脉络智能体的知识问答助手。请先检索用户知识库中的内容，再回答问题。\n"
        "回答要求：\n"
        "1. 明确标注「已收录知识」与「知识库未直接覆盖，基于已有知识推理」。\n"
        "2. 如果知识库中没有相关内容，直接说明，不要编造。\n"
        "3. 最后给出 2-3 个值得继续学习的相关方向。\n"
    )
    user = f"## 用户问题\n{question}\n\n## 知识库检索结果\n{context or '（未检索到相关内容）'}"
    if not config.DEEPSEEK_API_KEY:
        return _local_answer(question, context)
    try:
        llm = _get_llm()
        response = llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
        return response.content if hasattr(response, "content") else str(response)
    except Exception:
        return _local_answer(question, context)


@router.get("/health")
def health():
    ensure_database()
    return ok({"status": "healthy"})


@router.post("/graphs/generate")
def generate_graph(payload: GenerateRequest):
    try:
        result = get_graph_runner().invoke(
            _initial_state(
                payload.content,
                payload.output_format,
                payload.web_search_enabled,
            ),
            {"configurable": {"thread_id": "web"}},
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
        auto_links = _auto_link(graph_id, nodes)
    if graph_id:
        _generate_quiz(graph_id, nodes)
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
    """Start generation in a background job and return a pollable job id."""
    def runner() -> dict:
        result = get_graph_runner().invoke(
            _initial_state(
                payload.content,
                payload.output_format,
                payload.web_search_enabled,
                payload.selected_chapters,
            ),
            {"configurable": {"thread_id": f"web-{uuid.uuid4().hex}"}},
        )
        if result.get("error"):
            raise ApiError(result["error"], status=502)
        graph_id = result.get("current_graph_id", "")
        graph = repository.get_graph(graph_id) if graph_id else None
        nodes = repository.get_nodes(graph_id) if graph_id else []
        auto_links = []
        if payload.auto_link and graph_id:
            auto_links = _auto_link(graph_id, nodes)
        if graph_id:
            _generate_quiz(graph_id, nodes)
        return {
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
            from app.tools.doc_parser import parse_document
            parsed = parse_document(str(temp_path))
        finally:
            temp_path.unlink(missing_ok=True)
        if parsed.get("error"):
            raise ApiError(parsed["error"])
        from app.services.chunking import estimate_long_text
        return ok({
            "source_name": parsed.get("title") or (file.filename or ""),
            "content": parsed["content"],
            "preview": estimate_long_text(parsed["content"]),
        })
    if url:
        if _is_internal_url(url):
            raise ApiError("不允许访问内网地址")
        from app.tools.web_fetcher import fetch_url
        parsed = fetch_url(url)
        if parsed.get("error"):
            raise ApiError(parsed["error"])
        from app.services.chunking import estimate_long_text
        return ok({
            "source_name": parsed.get("url") or url,
            "content": parsed["content"],
            "preview": estimate_long_text(parsed["content"]),
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
    _hydrate_nodes(graph_id)
    nodes = repository.get_nodes(graph_id)
    return ok({
        "graph": graph,
        "nodes": nodes,
        "concept_links": _concept_links_for_nodes(nodes),
    })


@router.get("/graphs/{graph_id}/outline")
def get_outline(graph_id: str):
    if not repository.get_graph(graph_id):
        raise ApiError("脉络图不存在", status=404)
    _hydrate_nodes(graph_id)
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


@router.get("/concepts")
def list_concepts(graph_id: str = "", limit: int = 200):
    ensure_database()
    if graph_id:
        return ok(repository.get_concepts_for_graph(graph_id))
    return ok(repository.list_concepts(limit=min(limit, 1000)))


@router.post("/concepts/merge")
def merge_concepts(payload: ConceptMergeRequest):
    if not repository.merge_concepts(payload.winner_id, payload.loser_id):
        raise ApiError("概念合并失败，请检查概念 ID", status=400)
    return ok({"winner_id": payload.winner_id, "loser_id": payload.loser_id})


@router.get("/concepts/{concept_id}")
def get_concept(concept_id: str):
    concept = repository.get_concept(concept_id)
    if not concept:
        raise ApiError("概念不存在", status=404)
    return ok({
        "concept": concept,
        "mentions": repository.list_concept_mentions(concept_id),
        "links": repository.list_concept_links_for_concept(concept_id),
    })


@router.delete("/concepts/{concept_id}")
def delete_concept(concept_id: str):
    if not repository.delete_concept(concept_id):
        raise ApiError("概念不存在", status=404)
    return ok({"id": concept_id})


@router.get("/concept-links")
def list_concept_links(
    status: str = "",
    min_confidence: float = 0.0,
    limit: int = 200,
):
    return ok(repository.list_concept_links(
        limit=min(limit, 1000),
        status=status or None,
        min_confidence=min_confidence,
    ))


@router.get("/galaxy")
def get_galaxy():
    ensure_database()
    from app.services.domains import refresh_domains
    concepts = repository.list_concepts()
    existing_domains = repository.list_domains()
    domain_count = sum(int(d.get("concept_count") or 0) for d in existing_domains)
    domains = (
        refresh_domains()
        if not existing_domains or domain_count < len(concepts)
        else existing_domains
    )
    links = repository.list_concept_links(
        limit=10000,
        min_confidence=config.CONCEPT_LINK_MIN_CONFIDENCE,
    )
    mastery = repository.get_concept_mastery()
    for concept in concepts:
        concept["mastery"] = mastery.get(concept["id"], {
            "review_count": 0,
            "repetitions": 0,
            "mastery": "unseen",
            "retrievability": None,
            "last_reviewed_at": None,
        })
    return ok({
        "concepts": concepts,
        "links": links,
        "domains": domains,
        "mastery": mastery,
    })


@router.post("/domains/refresh")
def refresh_domains():
    from app.services.domains import refresh_domains as run_refresh
    return ok(run_refresh())


@router.get("/concepts/{start_id}/path/{end_id}")
def concept_path(start_id: str, end_id: str):
    from app.services.knowledge_path import explain_path, find_shortest_path
    path = find_shortest_path(start_id, end_id)
    if not path:
        return ok({"path": [], "explanation": "当前概念网络中没有连通路径"})
    return ok({
        "path": path,
        "explanation": explain_path(path),
    })


@router.patch("/concept-links/{link_id}")
def update_concept_link(link_id: str, payload: ConceptLinkStatusUpdate):
    if not repository.update_concept_link_status(link_id, payload.status):
        raise ApiError("概念链接不存在", status=404)
    return ok({"id": link_id, "status": payload.status})


@router.delete("/concept-links/{link_id}")
def delete_concept_link(link_id: str):
    if not repository.delete_concept_link(link_id):
        raise ApiError("概念链接不存在", status=404)
    return ok({"id": link_id})


@router.post("/graphs/{graph_id}/concepts/align")
def align_graph(graph_id: str):
    if not repository.get_graph(graph_id):
        raise ApiError("脉络图不存在", status=404)
    from app.services.concept_alignment import align_graph_nodes
    result = align_graph_nodes(graph_id)
    return ok(result.to_dict())


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


@router.post("/graphs/{graph_id}/quiz/generate")
def generate_quiz(graph_id: str):
    if not repository.get_graph(graph_id):
        raise ApiError("脉络图不存在", status=404)
    count = _generate_quiz(graph_id, repository.get_nodes(graph_id))
    return ok({"generated": count})


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
    if not repository.submit_review(review_id, payload.rating):
        raise ApiError("复习记录不存在", status=404)
    return ok({"id": review_id, "rating": payload.rating})


@router.get("/concepts/{concept_id}/curve")
def concept_curve(concept_id: str):
    concept = repository.get_concept(concept_id)
    if not concept:
        raise ApiError("概念不存在", status=404)
    return ok({
        "concept": concept,
        "history": repository.list_review_history(concept_id),
    })


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


@router.post("/ask")
def ask_knowledge(payload: AskRequest):
    ensure_database()
    context, sources = _build_knowledge_context(payload.question)
    if not payload.use_database:
        context = ""
        sources = []
    try:
        answer = _ask_llm(payload.question, context)
    except Exception as e:
        raise ApiError(f"知识问答失败: {e}", status=502)
    return ok({
        "question": payload.question,
        "answer": answer,
        "sources": sources,
        "has_sources": bool(sources),
    })
