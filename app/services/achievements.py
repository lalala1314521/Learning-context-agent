"""Achievement and streak service."""

from app.memory import repository


def get_achievements() -> list[dict]:
    concepts = repository.list_concepts()
    mastery = repository.get_concept_mastery()
    links = repository.list_concept_links(limit=10000, min_confidence=0.0)
    cross_links = [link for link in links if link["confidence"] >= 0.6]
    mastered = sum(1 for state in mastery.values() if state.get("mastery") == "strong")
    review_count = repository.count_review_history()
    achievements = [
        {
            "id": "first_concept",
            "name": "点亮第一颗星",
            "unlocked": len(concepts) >= 1,
            "progress": min(1, len(concepts) / 1),
        },
        {
            "id": "first_review",
            "name": "第一次复习",
            "unlocked": review_count >= 1,
            "progress": min(1, review_count / 1),
        },
        {
            "id": "network_builder",
            "name": "网络建设者",
            "unlocked": len(concepts) >= 10 and len(cross_links) >= 3,
            "progress": min(1, len(concepts) / 10),
        },
        {
            "id": "cross_doc",
            "name": "融会贯通",
            "unlocked": len(cross_links) >= 3,
            "progress": min(1, len(cross_links) / 3),
        },
        {
            "id": "master_ten",
            "name": "掌握十星",
            "unlocked": mastered >= 10,
            "progress": min(1, mastered / 10),
        },
    ]
    return achievements
