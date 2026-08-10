"""Import an Obsidian-style markdown vault as knowledge graphs."""

from pathlib import Path

from app.memory import repository
from app.tools.doc_parser import parse_document


def import_vault(vault_path: str, limit: int | None = None) -> dict:
    root = Path(vault_path)
    if not root.exists() or not root.is_dir():
        raise ValueError(f"目录不存在: {vault_path}")
    files = sorted(root.rglob("*.md"))
    if limit:
        files = files[:limit]
    imported = 0
    errors = []
    for path in files:
        try:
            parsed = parse_document(str(path))
            if parsed.get("error"):
                errors.append(str(path))
                continue
            graph_id = repository.create_graph(
                title=parsed.get("title") or path.stem,
                description="Obsidian 导入",
                graph_type="markdown",
                markdown_outline=parsed["content"],
                raw_content=parsed["content"],
                source_type="vault",
                source_name=str(path),
            )
            from app.services.longtext import map_reduce
            result = map_reduce(parsed["content"])
            for index, node in enumerate(result["node_payloads"]):
                repository.add_node(
                    graph_id,
                    label=node["label"],
                    note=node["note"],
                    node_type=node["node_type"],
                    order_index=index,
                    created_by="agent",
                )
            if result["chunks"]:
                repository.save_content_chunks(graph_id, result["chunks"])
            from app.services.concept_alignment import align_graph_nodes
            align_graph_nodes(graph_id)
            imported += 1
        except Exception as exc:
            errors.append(f"{path}: {exc}")
    return {
        "vault_path": str(root),
        "imported": imported,
        "files_found": len(files),
        "errors": errors[:20],
    }
