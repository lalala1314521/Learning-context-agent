"""One-shot migration: align all existing graph nodes into the concept layer."""

import argparse
import json

from app.memory.database import init_db
from app.services.concept_alignment import migrate_existing_graphs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    init_db()
    summary = migrate_existing_graphs(limit=args.limit)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(
            f"迁移完成：{summary['graphs']} 张脉络图，"
            f"{summary['aligned_mentions']} 个提及已对齐，"
            f"新增 {summary['new_concepts']} 个概念，"
            f"新增 {summary['new_links']} 条跨文档边。"
        )


if __name__ == "__main__":
    main()
