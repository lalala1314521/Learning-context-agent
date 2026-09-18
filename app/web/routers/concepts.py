"""/api/v1 概念层域路由：概念、概念链接、星图、领域、路径。"""

from fastapi import APIRouter

from app.config import config
from app.memory import repository
from app.web.dependencies import ensure_database
from app.web.routers.common import ApiError, ok
from app.web.schemas import ConceptLinkStatusUpdate, ConceptMergeRequest

router = APIRouter()


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


@router.get("/experience/overview")
def get_experience_overview():
    """一次读取新前端工作台所需的稳定数据契约。"""
    ensure_database()
    graphs = repository.list_graphs(limit=50)
    concepts = repository.list_concepts(limit=1000)
    links = repository.list_concept_links(limit=10000, min_confidence=0.0)
    return ok({
        "version": "knowledge-structure/v1",
        "graphs": graphs,
        "galaxy": {
            "concepts": concepts,
            "links": links,
            "domains": repository.list_domains(),
        },
        "capabilities": {
            "motion_modes": ["full", "light", "static"],
            "scenes": ["workspace", "materials", "knowledge", "galaxy", "ask", "review"],
        },
    })


@router.post("/domains/refresh")
def refresh_domains():
    from app.services.domains import refresh_domains as run_refresh
    return ok(run_refresh())


@router.get("/concepts/{start_id}/path/{end_id}")
def concept_path(start_id: str, end_id: str):
    from app.services.knowledge_path import explain_path, find_shortest_path_with_edges
    path, relations = find_shortest_path_with_edges(start_id, end_id)
    if not path:
        return ok({"path": [], "explanation": "当前概念网络中没有连通路径"})
    return ok({
        "path": path,
        "relations": relations,
        "explanation": explain_path(path, relations=relations),
    })


@router.get("/concepts/{concept_id}/curve")
def concept_curve(concept_id: str):
    concept = repository.get_concept(concept_id)
    if not concept:
        raise ApiError("概念不存在", status=404)
    return ok({
        "concept": concept,
        "history": repository.list_review_history(concept_id),
    })


@router.post("/graphs/{graph_id}/concepts/align")
def align_graph(graph_id: str):
    if not repository.get_graph(graph_id):
        raise ApiError("脉络图不存在", status=404)
    from app.services.concept_alignment import align_graph_nodes
    result = align_graph_nodes(graph_id)
    return ok(result.to_dict())
