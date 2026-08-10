"""/api/v1 路由：脉络、节点、记忆与内容解析。"""

import re
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile

from app.config import config
from app.graph.mermaid_parser import parse_graph_structure
from app.memory import repository
from app.web.dependencies import ensure_database, get_graph as get_graph_runner
from app.web.schemas import (
    AskRequest,
    GenerateRequest,
    GraphLinkCreate,
    GraphUpdate,
    NodeCreate,
    NodeUpdate,
    QuizCreate,
    ReviewSubmit,
)

router = APIRouter()

MAX_UPLOAD_BYTES = 50 * 1024 * 1024


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def ok(data):
    return {"ok": True, "data": data, "error": None}


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


def _initial_state(content: str, output_format: str, web_search: bool) -> dict:
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
    return "\n\n".join(parts)[:8000], sources


def _ask_llm(question: str, context: str):
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_deepseek import ChatDeepSeek

    system = (
        "你是学习脉络智能体的知识问答助手。请先检索用户知识库中的内容，再回答问题。\n"
        "回答要求：\n"
        "1. 明确标注「已收录知识」与「知识库未直接覆盖，基于已有知识推理」。\n"
        "2. 如果知识库中没有相关内容，直接说明，不要编造。\n"
        "3. 最后给出 2-3 个值得继续学习的相关方向。\n"
    )
    user = f"## 用户问题\n{question}\n\n## 知识库检索结果\n{context or '（未检索到相关内容）'}"
    llm = ChatDeepSeek(
        model=config.DEEPSEEK_CHAT_MODEL,
        api_key=config.DEEPSEEK_API_KEY,
        api_base=config.DEEPSEEK_BASE_URL,
        temperature=0.3,
    )
    response = llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
    return response.content if hasattr(response, "content") else str(response)


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
        "nodes": nodes,
        "auto_links": auto_links,
    })


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
            raise ApiError("文件超过 20MB 限制")
        suffix = Path(file.filename or "").suffix.lower()
        if not suffix:
            raise ApiError("无法识别文件类型")
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
        return ok({
            "source_name": parsed.get("title") or (file.filename or ""),
            "content": parsed["content"][:config.MAX_CONTENT_LENGTH],
        })
    if url:
        from app.tools.web_fetcher import fetch_url
        parsed = fetch_url(url)
        if parsed.get("error"):
            raise ApiError(parsed["error"])
        return ok({
            "source_name": parsed.get("url") or url,
            "content": parsed["content"][:config.MAX_CONTENT_LENGTH],
        })
    if text is not None:
        return ok({"source_name": "", "content": text[:config.MAX_CONTENT_LENGTH]})
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
    return ok({"graph": graph, "nodes": repository.get_nodes(graph_id)})


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


@router.post("/review/{review_id}")
def submit_review(review_id: str, payload: ReviewSubmit):
    if not repository.submit_review(review_id, payload.rating):
        raise ApiError("复习记录不存在", status=404)
    return ok({"id": review_id, "rating": payload.rating})


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
