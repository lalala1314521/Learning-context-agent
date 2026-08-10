"""Concept alignment pipeline: mentions -> global concepts -> concept links."""

import re
from dataclasses import dataclass, field

from app.config import config
from app.memory import repository
from app.memory.embeddings import (
    cosine_similarity,
    decode_embedding,
    embed_text,
)
from app.services.llm import invoke_structured

_PUNCT_RE = re.compile(r"[\s_\-—:：,，.。;；!！?？()（）\[\]【】]+")


@dataclass
class AlignmentResult:
    graph_id: str
    aligned: int = 0
    new_concepts: list[dict] = field(default_factory=list)
    reinforced: list[dict] = field(default_factory=list)
    new_links: list[dict] = field(default_factory=list)
    pending_links: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "graph_id": self.graph_id,
            "aligned_mentions": self.aligned,
            "new_concepts": self.new_concepts,
            "reinforced_concepts": self.reinforced,
            "new_links": self.new_links,
            "pending_links": self.pending_links,
            "errors": self.errors,
        }


def _normalize(label: str) -> str:
    return _PUNCT_RE.sub("", (label or "").strip().lower())


def _mention_vector(label: str, note: str = "") -> list[float]:
    text = f"{label}\n{note}" if note.strip() else label
    return embed_text(text)


def _top_candidates(
    vector: list[float],
    exclude_ids: set[str] | None = None,
    top_k: int = 5,
) -> list[tuple[dict, float]]:
    concepts = repository.list_concepts(include_embedding=True)
    scored: list[tuple[dict, float]] = []
    exclude_ids = exclude_ids or set()
    for concept in concepts:
        if concept["id"] in exclude_ids:
            continue
        sim = cosine_similarity(vector, decode_embedding(concept.get("embedding")))
        scored.append((concept, sim))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:top_k]


def _disambiguate_with_llm(
    label: str,
    note: str,
    candidates: list[tuple[dict, float]],
    llm=None,
) -> dict | None:
    rows = "\n".join(
        f"- id: {c['id']}, label: {c['canonical_label']}, "
        f"summary: {(c.get('summary') or '')[:160]}, similarity: {sim:.3f}"
        for c, sim in candidates
    )
    prompt = (
        "你是知识概念消歧器。判断新提及与候选概念是否是同一概念，不要只看字符串，"
        "要结合语义。只输出 JSON："
        '{"same_concept": true|false, "canonical_label": "...", "reason": "..."}\n\n'
        f"新提及 label: {label}\nnote: {(note or '')[:300]}\n\n候选概念:\n{rows}"
    )
    data = invoke_structured(prompt, llm=llm, retries=1)
    if not data or not isinstance(data, dict):
        return None
    return data


def _match_concept(
    label: str,
    note: str,
    vector: list[float],
    llm=None,
) -> tuple[str | None, str, float]:
    """Return concept_id, decision, similarity."""
    normalized = _normalize(label)
    if normalized:
        exact = repository.find_concept_by_alias(normalized) or repository.find_concept_by_alias(label)
        if exact:
            return exact["id"], "exact", 1.0
    candidates = _top_candidates(vector)
    if not candidates:
        return None, "new", 0.0
    top_id, top_sim = candidates[0]
    if top_sim >= 0.92:
        return top_id, "vector_high", top_sim
    gray = [(c, sim) for c, sim in candidates if sim >= 0.75]
    if gray and config.CONCEPT_LLM_DISAMBIGUATION:
        decision = _disambiguate_with_llm(label, note, gray, llm=llm)
        if decision and decision.get("same_concept") is True:
            canonical = str(decision.get("canonical_label") or "").strip()
            target = next(
                (
                    c for c, _ in gray
                    if c["canonical_label"] == canonical
                    or canonical in c.get("aliases", [])
                ),
                gray[0][0],
            )
            return target["id"], "llm_same", top_sim
    return None, "new", top_sim


def _summary_merge(existing: str, note: str) -> str:
    note = (note or "").strip()
    if not note:
        return existing or ""
    if existing and note in existing:
        return existing
    if existing:
        return f"{existing}\n{note}"[:2000]
    return note[:2000]


def _shared_bigram(a: str, b: str) -> bool:
    def grams(text: str) -> set[str]:
        compact = _PUNCT_RE.sub("", (text or "").lower())
        return {
            compact[i:i + 2]
            for i in range(len(compact) - 1)
            if not compact[i:i + 2].isdigit()
        }

    return bool(grams(a) & grams(b))


def _propose_links(
    graph_id: str,
    aligned: list[dict],
    result: AlignmentResult,
    llm=None,
) -> None:
    """Create concept links across graphs using LLM when available."""
    if not aligned:
        return
    all_graphs = repository.list_graphs(limit=500)
    candidates: list[dict] = []
    for graph in all_graphs:
        if graph["id"] == graph_id:
            continue
        for node in repository.get_nodes(graph["id"]):
            if not node.get("concept_id"):
                continue
            for current in aligned:
                if current["concept_id"] == node["concept_id"]:
                    continue
                candidates.append({
                    "from_concept": current["concept_id"],
                    "from_label": current["label"],
                    "from_graph": graph_id,
                    "to_concept": node["concept_id"],
                    "to_label": node["label"],
                    "to_graph": graph["id"],
                    "to_graph_title": graph["title"],
                })
    if not candidates:
        return
    seen = set()
    for candidate in candidates:
        key = (candidate["from_concept"], candidate["to_concept"])
        reverse = (candidate["to_concept"], candidate["from_concept"])
        if key in seen or reverse in seen:
            continue
        seen.add(key)
        from_vec = _mention_vector(candidate["from_label"])
        to_vec = _mention_vector(candidate["to_label"])
        sim = cosine_similarity(from_vec, to_vec)
        shared = _shared_bigram(
            candidate["from_label"], candidate["to_label"]
        )
        if sim < 0.25 and not shared:
            continue
        confidence = round(max(0.55, 0.5 + sim * 0.4), 2)
        relation_type = "related"
        evidence = (
            f"《{candidate['to_graph_title']}》中的「{candidate['to_label']}」"
            f"与本次「{candidate['from_label']}」语义相似（{sim:.2f}）"
        )
        link_id = repository.create_concept_link(
            from_concept=candidate["from_concept"],
            to_concept=candidate["to_concept"],
            relation_type=relation_type,
            confidence=confidence,
            evidence=evidence,
            source="rule",
            status="confirmed" if sim >= 0.75 else "pending",
        )
        if link_id:
            result.new_links.append({
                "id": link_id,
                "from_concept": candidate["from_concept"],
                "from_label": candidate["from_label"],
                "to_concept": candidate["to_concept"],
                "to_label": candidate["to_label"],
                "to_graph_id": candidate["to_graph"],
                "to_graph_title": candidate["to_graph_title"],
                "relation_type": relation_type,
                "confidence": confidence,
            })
        if len(result.new_links) >= config.MAX_CONCEPT_LINKS_PER_GRAPH:
            break


def align_graph_nodes(
    graph_id: str,
    nodes: list[dict] | None = None,
    llm=None,
) -> AlignmentResult:
    """Align all graph nodes into the global concept layer."""
    result = AlignmentResult(graph_id=graph_id)
    if not graph_id:
        return result
    nodes = nodes if nodes is not None else repository.get_nodes(graph_id)
    if not nodes:
        return result

    graph = repository.get_graph(graph_id) or {}
    for node in nodes:
        label = (node.get("label") or "").strip()
        if not label:
            continue
        note = node.get("note") or ""
        vector = _mention_vector(label, note)
        concept_id, decision, sim = _match_concept(label, note, vector, llm=llm)
        if not concept_id:
            concept_id = repository.create_concept(
                canonical_label=label,
                summary=note or label,
                embedding=vector,
            )
            result.new_concepts.append({
                "id": concept_id,
                "label": label,
                "source_graph_id": graph_id,
                "source_graph_title": graph.get("title") or "",
                "decision": decision,
            })
        else:
            concept = repository.get_concept(concept_id)
            if concept:
                repository.update_concept(
                    concept_id,
                    summary=_summary_merge(concept.get("summary") or "", note),
                    embedding=vector,
                    mention_count=int(concept.get("mention_count") or 0) + 1,
                )
            repository.add_concept_alias(concept_id, label)
            result.reinforced.append({
                "id": concept_id,
                "label": label,
                "mention_count": int((concept or {}).get("mention_count") or 0) + 1,
                "decision": decision,
            })
        repository.update_node(node["id"], concept_id=concept_id)
        result.aligned += 1

    aligned = [
        {
            "id": node["id"],
            "label": node.get("label"),
            "concept_id": node.get("concept_id"),
            "note": node.get("note"),
            "graph_id": graph_id,
        }
        for node in repository.get_nodes(graph_id)
        if node.get("concept_id")
    ]
    try:
        _propose_links(graph_id, aligned, result, llm=llm)
    except Exception as exc:
        result.errors.append(f"concept link proposal failed: {exc}")
    return result


def migrate_existing_graphs(limit: int | None = None) -> dict:
    """Run alignment over all existing graphs (used by migration script)."""
    graphs = repository.list_graphs(limit=limit or 500)
    summary = {
        "graphs": len(graphs),
        "aligned_mentions": 0,
        "new_concepts": 0,
        "new_links": 0,
    }
    for graph in graphs:
        nodes = repository.get_nodes(graph["id"])
        if not nodes:
            from app.web.api import _hydrate_nodes
            try:
                _hydrate_nodes(graph["id"])
                nodes = repository.get_nodes(graph["id"])
            except Exception:
                continue
        result = align_graph_nodes(graph["id"], nodes=nodes)
        summary["aligned_mentions"] += result.aligned
        summary["new_concepts"] += len(result.new_concepts)
        summary["new_links"] += len(result.new_links)
    return summary
