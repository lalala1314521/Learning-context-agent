"""Map-Reduce long-text pipeline and book chapterization."""

import re
from concurrent.futures import ThreadPoolExecutor

from app.config import config
from app.memory import repository
from app.memory.embeddings import embed_texts
from app.services.chunking import chunk_content, detect_chapters
from app.services.llm import invoke_structured

_MAP_PROMPT = """你是知识脉络抽取器。请从下面文本中提取概念和关系，只输出 JSON：
{{
  "concepts": [{{"label": "概念名", "note": "一句话解释或关键原文", "node_type": "concept|method|case|formula|conclusion"}}],
  "relations": [{{"from": "概念名", "to": "概念名", "relation_type": "depends|related|contrast|extends|cause", "evidence": "原文依据"}}]
}}
不要输出 Markdown，不要输出 JSON 以外的内容。

文本：
{content}"""

_REDUCE_PROMPT = """你是脉络图整合器。根据归并后的概念清单和关系，生成一份完整的 Mermaid
流程/层级图与 Markdown 大纲。只输出 JSON：
{{"mermaid": "...", "markdown": "...", "title": "..."}}

概念清单：
{concepts}

关系清单：
{relations}"""

_RELATION_ALIASES = {
    "depends": "depends_on",
    "dependency": "depends_on",
    "extends": "supports",
    "cause": "causes",
    "contrast": "contrasts",
}


def _fallback_extract(content: str) -> tuple[list[dict], list[dict]]:
    concepts: list[dict] = []
    relations: list[dict] = []
    seen: set[str] = set()
    for raw in content.splitlines():
        line = raw.strip()
        if not line:
            continue
        label = re.sub(r"^#{1,6}\s+", "", line).strip("*-")
        if not label or len(label) > 60 or label.endswith(("。", "；", "，", ",")):
            continue
        if label not in seen:
            seen.add(label)
            concepts.append({
                "label": label,
                "note": "",
                "node_type": "concept",
            })
    # 只有原文明确出现关系触发词时才建立边；相邻标题不构成知识依据。
    trigger = re.compile(r"([^。；，,\s]{2,30})\s*(依赖|导致|引起|包含|包括|属于|基于|区别于|对比)\s*([^。；，,\s]{2,30})")
    for match in trigger.finditer(content):
        for endpoint in (match.group(1).strip(), match.group(3).strip()):
            if endpoint and endpoint not in seen and len(endpoint) <= 60:
                seen.add(endpoint)
                concepts.append({"label": endpoint, "note": "", "node_type": "concept"})
        relation_type = {
            "依赖": "depends_on", "导致": "causes", "引起": "causes",
            "包含": "supports", "包括": "supports", "属于": "related",
            "基于": "depends_on", "区别于": "contrasts", "对比": "contrasts",
        }[match.group(2)]
        relations.append({
            "from": match.group(1).strip(),
            "to": match.group(3).strip(),
            "relation_type": relation_type,
            "evidence": match.group(0).strip(),
        })
    return concepts[:80], relations[:80]


def _extract_chunk(content: str, llm=None) -> tuple[list[dict], list[dict]]:
    if llm is None:
        return _fallback_extract(content)
    data = invoke_structured(
        _MAP_PROMPT.format(content=content[:config.SINGLE_LLM_CHUNK_LIMIT]),
        llm=llm,
        retries=1,
    )
    if not data:
        return _fallback_extract(content)
    concepts = []
    seen = set()
    for item in data.get("concepts", []) if isinstance(data, dict) else []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        if not label or label in seen:
            continue
        seen.add(label)
        concepts.append({
            "label": label,
            "note": str(item.get("note") or "").strip(),
            "node_type": str(item.get("node_type") or "concept"),
        })
    relations = []
    seen_relations = set()
    for item in data.get("relations", []) if isinstance(data, dict) else []:
        if not isinstance(item, dict):
            continue
        key = (item.get("from"), item.get("to"), item.get("relation_type"))
        if key in seen_relations:
            continue
        seen_relations.add(key)
        raw_type = str(item.get("relation_type") or "related").strip().lower()
        relations.append({
            "from": str(item.get("from") or ""),
            "to": str(item.get("to") or ""),
            "relation_type": _RELATION_ALIASES.get(raw_type, raw_type),
            "evidence": str(item.get("evidence") or ""),
        })
    return concepts or _fallback_extract(content)[0], relations


def _parallel_extract(texts: list[str], llm=None) -> list[tuple[list[dict], list[dict]]]:
    if llm is None or len(texts) <= 1:
        return [_extract_chunk(text, llm=llm) for text in texts]
    with ThreadPoolExecutor(max_workers=min(4, len(texts))) as pool:
        return list(pool.map(lambda text: _extract_chunk(text, llm=llm), texts))


def _merge_extractions(results: list[tuple[list[dict], list[dict]]]) -> tuple[list[dict], list[dict]]:
    concepts: dict[str, dict] = {}
    relations: dict[tuple[str, str, str], dict] = {}
    for chunk_concepts, chunk_relations in results:
        for concept in chunk_concepts:
            label = (concept.get("label") or "").strip()
            if not label:
                continue
            normalized = re.sub(r"\s+", "", label.lower())
            if normalized in concepts:
                note = concept.get("note") or ""
                if note and note not in concepts[normalized].get("note", ""):
                    concepts[normalized]["note"] = (
                        f"{concepts[normalized].get('note', '')} {note}".strip()
                    )
            else:
                concepts[normalized] = dict(concept)
        for relation in chunk_relations:
            key = (
                relation.get("from", "").strip(),
                relation.get("to", "").strip(),
                relation.get("relation_type", "related"),
            )
            if not key[0] or not key[1]:
                continue
            relations.setdefault(key, {
                "from": key[0],
                "to": key[1],
                "relation_type": _RELATION_ALIASES.get(key[2], key[2]),
                "evidence": relation.get("evidence", ""),
            })
    return list(concepts.values()), list(relations.values())


def _fallback_mermaid(concepts: list[dict], relations: list[dict]) -> tuple[str, str]:
    lines = ["graph TD"]
    index = 0
    for concept in concepts[:60]:
        lines.append(f'    N{index}["{concept["label"][:30]}"]')
        index += 1
    by_label = {c["label"]: f"N{i}" for i, c in enumerate(concepts[:60])}
    for relation in relations[:80]:
        source = by_label.get(relation.get("from"))
        target = by_label.get(relation.get("to"))
        if source and target and source != target:
            lines.append(f"    {source} --> {target}")
    markdown = "\n".join(
        f"- {c['label']}" + (f"：{c['note']}" if c.get("note") else "")
        for c in concepts[:80]
    )
    return "\n".join(lines), f"# 长文本脉络\n{markdown}"


def map_reduce(content: str, llm=None) -> dict:
    chunks = chunk_content(content)
    results = _parallel_extract([c["text"] for c in chunks], llm=llm)
    concepts, relations = _merge_extractions(results)
    mermaid = ""
    markdown = ""
    title = ""
    if llm is not None:
        concept_text = "\n".join(
            f"- {c['label']}: {c.get('note', '')[:120]}"
            for c in concepts[:80]
        )
        relation_text = "\n".join(
            f"- {r['from']} --{r['relation_type']}--> {r['to']}"
            for r in relations[:80]
        )
        data = invoke_structured(
            _REDUCE_PROMPT.format(concepts=concept_text, relations=relation_text),
            llm=llm,
            retries=1,
        )
        if data:
            mermaid = str(data.get("mermaid") or "").strip()
            markdown = str(data.get("markdown") or "").strip()
            title = str(data.get("title") or "").strip()
    if not mermaid:
        mermaid, markdown = _fallback_mermaid(concepts, relations)
    node_payloads = []
    node_ids = {
        re.sub(r"\s+", "", concept["label"].lower()): f"N{index}"
        for index, concept in enumerate(concepts[:120])
    }
    relation_by_source: dict[str, list[dict]] = {}
    for relation in relations:
        source_id = node_ids.get(re.sub(r"\s+", "", relation.get("from", "").lower()))
        target_id = node_ids.get(re.sub(r"\s+", "", relation.get("to", "").lower()))
        if not source_id or not target_id or source_id == target_id:
            continue
        relation_by_source.setdefault(source_id, []).append({"id": target_id, **relation})
    for index, concept in enumerate(concepts[:120]):
        node_id = f"N{index}"
        outgoing = relation_by_source.get(node_id, [])
        node_payloads.append({
            "id": node_id,
            "label": concept["label"],
            "note": concept.get("note", "") or (outgoing[0].get("evidence", "") if outgoing else ""),
            "node_type": concept.get("node_type", "concept"),
            "parent_id": "",
            "related_nodes": [item["id"] for item in outgoing],
            "evidence": "；".join(item.get("evidence", "") for item in outgoing if item.get("evidence")),
            "relation_type": outgoing[0].get("relation_type", "related") if outgoing else "related",
            "order_index": index,
        })
    embeddings = embed_texts([c["text"] for c in chunks])
    for chunk, vector in zip(chunks, embeddings):
        chunk["embedding"] = vector
    return {
        "mermaid": mermaid,
        "markdown": markdown,
        "title": title,
        "node_payloads": node_payloads,
        "chunks": chunks,
        "concepts": concepts,
        "relations": relations,
        "report": {
            "tier": "M",
            "chunks": len(chunks),
            "concepts": len(concepts),
            "relations": len(relations),
        },
    }


def prepare_book_payload(
    content: str,
    llm=None,
    selected_indices: list[int] | None = None,
) -> dict:
    chapters = detect_chapters(content)
    selected = (
        [chapters[i] for i in selected_indices if 0 <= i < len(chapters)]
        if selected_indices
        else chapters
    )
    chapter_payloads = []
    for chapter in selected:
        result = map_reduce(chapter["text"], llm=llm)
        chapter_payloads.append({
            "title": chapter["title"],
            "text": chapter["text"],
            "char_start": chapter["char_start"],
            "char_end": chapter["char_end"],
            **result,
        })
    lines = ["graph TD"]
    for index, chapter in enumerate(chapter_payloads):
        safe = chapter["title"].replace('"', "'")[:40]
        lines.append(f'    C{index}["{safe}"]')
        if index:
            lines.append(f"    C{index - 1} --> C{index}")
    markdown = "\n".join(f"## {c['title']}" for c in chapter_payloads)
    return {
        "mermaid": "\n".join(lines),
        "markdown": markdown,
        "title": "全书章节脉络",
        "chapter_payloads": chapter_payloads,
        "report": {
            "tier": "L",
            "chapters": len(chapter_payloads),
            "total_chapters": len(chapters),
            "chunks": sum(len(c["chunks"]) for c in chapter_payloads),
        },
    }


def create_book_subgraphs(mother_graph_id: str, chapter_payloads: list[dict]) -> list[dict]:
    created = []
    for payload in chapter_payloads:
        graph_id = repository.create_graph(
            title=payload["title"],
            description="长文档章节子图",
            graph_type="auto",
            mermaid_code=payload.get("mermaid", ""),
            markdown_outline=payload.get("markdown", ""),
            raw_content=payload.get("text", ""),
            source_type="long_text",
            source_name=payload["title"],
            parent_graph_id=mother_graph_id,
        )
        for index, node in enumerate(payload.get("node_payloads", [])):
            repository.add_node(
                graph_id,
                label=node.get("label", ""),
                note=node.get("note", ""),
                node_type=node.get("node_type", "concept"),
                parent_id=node.get("parent_id") or None,
                related_nodes=node.get("related_nodes", []),
                order_index=int(node.get("order_index", index)),
                created_by="agent",
            )
        if payload.get("chunks"):
            repository.save_content_chunks(graph_id, payload["chunks"])
        created.append({
            "graph_id": graph_id,
            "title": payload["title"],
            "chunks": len(payload.get("chunks", [])),
            "concepts": len(payload.get("node_payloads", [])),
        })
    return created
