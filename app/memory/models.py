"""数据模型定义与建表 SQL。"""

DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS knowledge_graphs (
        id               TEXT PRIMARY KEY,
        title            TEXT NOT NULL,
        description      TEXT,
        graph_type       TEXT DEFAULT 'auto',
        mermaid_code     TEXT,
        markdown_outline TEXT,
        raw_content      TEXT,
        source_type      TEXT,
        source_name      TEXT,
        tags             TEXT,
        created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_nodes (
        id            TEXT PRIMARY KEY,
        graph_id      TEXT NOT NULL REFERENCES knowledge_graphs(id) ON DELETE CASCADE,
        parent_id     TEXT REFERENCES graph_nodes(id) ON DELETE SET NULL,
        label         TEXT NOT NULL,
        note          TEXT,
        node_type     TEXT DEFAULT 'concept',
        related_nodes TEXT,
        order_index   INTEGER DEFAULT 0,
        created_by    TEXT DEFAULT 'agent',
        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_snapshots (
        id         TEXT PRIMARY KEY,
        graph_id   TEXT REFERENCES knowledge_graphs(id) ON DELETE SET NULL,
        summary    TEXT NOT NULL,
        key_points TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_graph_nodes_graph ON graph_nodes(graph_id)",
    "CREATE INDEX IF NOT EXISTS idx_memory_snapshots_graph ON memory_snapshots(graph_id)",
    """
    CREATE TABLE IF NOT EXISTS graph_links (
        id            TEXT PRIMARY KEY,
        from_graph_id TEXT REFERENCES knowledge_graphs(id) ON DELETE CASCADE,
        from_node_id  TEXT REFERENCES graph_nodes(id) ON DELETE CASCADE,
        to_graph_id   TEXT REFERENCES knowledge_graphs(id) ON DELETE CASCADE,
        to_node_id    TEXT REFERENCES graph_nodes(id) ON DELETE CASCADE,
        relation_type TEXT DEFAULT 'related',
        note          TEXT,
        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_graph_links_from ON graph_links(from_graph_id)",
    "CREATE INDEX IF NOT EXISTS idx_graph_links_to ON graph_links(to_graph_id)",
    """
    CREATE TABLE IF NOT EXISTS quiz_questions (
        id            TEXT PRIMARY KEY,
        graph_id      TEXT REFERENCES knowledge_graphs(id) ON DELETE CASCADE,
        node_id       TEXT REFERENCES graph_nodes(id) ON DELETE CASCADE,
        question      TEXT NOT NULL,
        answer        TEXT NOT NULL,
        question_type TEXT DEFAULT 'short_answer',
        difficulty    INTEGER DEFAULT 1,
        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_quiz_graph ON quiz_questions(graph_id)",
    """
    CREATE TABLE IF NOT EXISTS review_progress (
        id                TEXT PRIMARY KEY,
        graph_id          TEXT REFERENCES knowledge_graphs(id) ON DELETE CASCADE,
        node_id           TEXT REFERENCES graph_nodes(id) ON DELETE CASCADE,
        quiz_id           TEXT REFERENCES quiz_questions(id) ON DELETE CASCADE,
        status            TEXT DEFAULT 'new',
        repetitions       INTEGER DEFAULT 0,
        interval_days     INTEGER DEFAULT 1,
        ease_factor       REAL DEFAULT 2.5,
        due_at            TIMESTAMP,
        last_reviewed_at  TIMESTAMP,
        updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_review_due ON review_progress(due_at)",
]
