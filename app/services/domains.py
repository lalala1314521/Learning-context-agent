"""Domain detection over the global concept graph."""

from collections import Counter

from app.memory import repository

_PALETTE = [
    "#4A8DFF", "#10B981", "#FF7A45", "#F59E0B",
    "#7B5CD6", "#EC4899", "#14B8A6", "#8B5CF6",
]


def refresh_domains() -> list[dict]:
    """Refresh domain clusters with label propagation and persist them."""
    concepts = repository.list_concepts()
    if not concepts:
        return []
    links = repository.list_concept_links(limit=100000, min_confidence=0.0)
    by_id = {c["id"]: c for c in concepts}
    adjacency: dict[str, set[str]] = {c["id"]: set() for c in concepts}
    for link in links:
        a, b = link["from_concept"], link["to_concept"]
        if a in adjacency and b in adjacency:
            adjacency[a].add(b)
            adjacency[b].add(a)

    labels = {cid: cid for cid in by_id}
    for _ in range(24):
        changed = False
        for cid in list(by_id):
            neighbor_labels = Counter(labels[n] for n in adjacency[cid])
            if not neighbor_labels:
                continue
            chosen = neighbor_labels.most_common(1)[0][0]
            if labels[cid] != chosen:
                labels[cid] = chosen
                changed = True
        if not changed:
            break

    clusters: dict[str, list[str]] = {}
    for cid, label in labels.items():
        clusters.setdefault(label, []).append(cid)

    domains: list[dict] = []
    for index, members in enumerate(clusters.values()):
        degree = {
            cid: len(adjacency[cid]) for cid in members
        }
        representative = max(members, key=lambda cid: (
            degree[cid],
            int(by_id[cid].get("mention_count") or 0),
        ))
        name = by_id[representative]["canonical_label"] or f"领域 {index + 1}"
        domain_id = repository.create_domain(name, _PALETTE[index % len(_PALETTE)])
        for cid in members:
            repository.update_concept(cid, domain_id=domain_id)
        repository.update_domain_count(domain_id, len(members))
        domains.append({
            "id": domain_id,
            "name": name,
            "color": _PALETTE[index % len(_PALETTE)],
            "concept_count": len(members),
        })
    return domains
