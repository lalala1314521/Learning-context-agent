"""Anki .apkg export through the optional genanki library."""


def build_apkg_bytes() -> bytes:
    try:
        import genanki
    except ImportError:
        raise RuntimeError(
            "genanki 未安装，请先执行 uv sync --extra v2 后重试"
        )
    from io import BytesIO

    model = genanki.Model(
        1607392319,
        "Learning Context Agent",
        fields=[
            {"name": "Front"},
            {"name": "Back"},
        ],
        templates=[
            {
                "name": "Card 1",
                "qfmt": "{{Front}}",
                "afmt": "{{FrontSide}}<hr id=answer>{{Back}}",
            },
        ],
    )
    deck = genanki.Deck(2059400110, "Learning Context Agent")
    concepts = _concept_pairs()
    for front, back in concepts:
        deck.add_note(genanki.Note(model=model, fields=[front, back]))
    package = genanki.Package(deck)
    buffer = BytesIO()
    package.write_to_file(buffer)
    return buffer.getvalue()


def _concept_pairs() -> list[tuple[str, str]]:
    from app.memory import repository
    pairs = []
    for concept in repository.list_concepts(limit=500):
        pairs.append((
            concept["canonical_label"],
            concept.get("summary") or concept["canonical_label"],
        ))
    return pairs
