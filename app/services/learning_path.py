"""Learning path planning from dependency edges on the concept graph."""

from collections import deque

from app.memory import repository

_DEPENDENCY_TYPES = {"depends", "extends", "prerequisite", "cause"}


def build_learning_path(
    target_id: str,
    max_depth: int = 6,
) -> list[dict]:
    target = repository.get_concept(target_id)
    if not target:
        return []
    links = repository.list_concept_links(limit=100000, min_confidence=0.0)
    incoming: dict[str, list[str]] = {}
    for link in links:
        if link["relation_type"] not in _DEPENDENCY_TYPES:
            continue
        incoming.setdefault(link["to_concept"], []).append(link["from_concept"])

    depth: dict[str, int] = {target_id: 0}
    queue = deque([target_id])
    while queue:
        current = queue.popleft()
        if depth[current] >= max_depth:
            continue
        for predecessor in incoming.get(current, []):
            if predecessor in depth:
                continue
            depth[predecessor] = depth[current] + 1
            queue.append(predecessor)

    path_ids = sorted(depth, key=lambda cid: (depth[cid], cid))
    path = [
        c for c in (repository.get_concept(cid) for cid in path_ids) if c
    ]
    mastery = repository.get_concept_mastery()
    for concept in path:
        state = mastery.get(concept["id"], {})
        concept["learning_status"] = state.get("mastery", "new")
        concept["retrievability"] = state.get("retrievability")
    return path


def resolve_target(query: str) -> dict | None:
    exact = repository.find_concept_by_alias(query)
    if exact:
        return exact
    matches = repository.search_concepts(query, limit=1)
    return matches[0] if matches else None
