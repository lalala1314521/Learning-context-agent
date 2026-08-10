"""Weekly knowledge network report."""

from datetime import date

from app.memory import repository


def generate_weekly_report() -> dict:
    new_concepts = repository.count_concepts_created_since(days=7)
    new_links = repository.count_concept_links_created_since(days=7)
    concepts = repository.list_concepts()
    mastery = repository.get_concept_mastery()
    ranked = sorted(
        mastery.items(),
        key=lambda item: float(item[1].get("retrievability") or 0),
        reverse=True,
    )
    top5 = []
    for concept_id, state in ranked[:5]:
        concept = repository.get_concept(concept_id)
        if concept:
            top5.append({
                "concept_id": concept_id,
                "label": concept["canonical_label"],
                "retrievability": state.get("retrievability"),
                "mastery": state.get("mastery"),
            })
    due_count = len(repository.get_due_review(limit=1000))
    domains = repository.list_domains()
    return {
        "week_end": date.today().isoformat(),
        "new_concepts": new_concepts,
        "new_links": new_links,
        "total_concepts": len(concepts),
        "mastery_top5": top5,
        "active_domains": domains[:5],
        "next_week_review_pressure": due_count,
    }
