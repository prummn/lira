"""Baseline compatible with the original unversioned SQLite skeleton."""

from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None

TABLES = {
    "papers": "id VARCHAR(64) PRIMARY KEY, title VARCHAR(500) NOT NULL, abstract TEXT, year INTEGER, venue VARCHAR(200), doi VARCHAR(200) UNIQUE, arxiv_id VARCHAR(100), pdf_path VARCHAR(1000), reading_status VARCHAR(32) NOT NULL DEFAULT 'unread', is_favorite BOOLEAN NOT NULL DEFAULT 0, analysis_status VARCHAR(32) NOT NULL DEFAULT 'pending', tags_json TEXT NOT NULL DEFAULT '[]', created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL",
    "authors": "id VARCHAR(64) PRIMARY KEY, name VARCHAR(200) NOT NULL, affiliation VARCHAR(300)",
    "paper_authors": "paper_id VARCHAR(64) REFERENCES papers(id) ON DELETE CASCADE, author_id VARCHAR(64) REFERENCES authors(id) ON DELETE CASCADE, order_index INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(paper_id,author_id)",
    "collections": "id VARCHAR(64) PRIMARY KEY, name VARCHAR(200) UNIQUE NOT NULL, description TEXT, color VARCHAR(32) NOT NULL DEFAULT '#5B6CFF', created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL",
    "collection_papers": "collection_id VARCHAR(64) REFERENCES collections(id) ON DELETE CASCADE, paper_id VARCHAR(64) REFERENCES papers(id) ON DELETE CASCADE, PRIMARY KEY(collection_id,paper_id)",
    "paper_chunks": "id VARCHAR(64) PRIMARY KEY, paper_id VARCHAR(64) NOT NULL REFERENCES papers(id) ON DELETE CASCADE, page INTEGER, section VARCHAR(100), content TEXT NOT NULL",
    "paper_analysis": "paper_id VARCHAR(64) PRIMARY KEY REFERENCES papers(id) ON DELETE CASCADE, one_liner TEXT, problem TEXT, method TEXT, findings TEXT, limitations TEXT, concepts_json TEXT NOT NULL DEFAULT '[]'",
    "evidence": "id VARCHAR(64) PRIMARY KEY, paper_id VARCHAR(64) NOT NULL REFERENCES papers(id) ON DELETE CASCADE, claim TEXT NOT NULL, source_text TEXT NOT NULL, page INTEGER, section VARCHAR(100), confidence FLOAT NOT NULL DEFAULT 0.9, source_type VARCHAR(32) NOT NULL DEFAULT 'explicit'",
    "notes": "id VARCHAR(64) PRIMARY KEY, paper_id VARCHAR(64) NOT NULL REFERENCES papers(id) ON DELETE CASCADE, content TEXT NOT NULL, page INTEGER, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL",
    "edges": "id VARCHAR(64) PRIMARY KEY, source_paper_id VARCHAR(64) NOT NULL REFERENCES papers(id) ON DELETE CASCADE, target_paper_id VARCHAR(64) NOT NULL REFERENCES papers(id) ON DELETE CASCADE, relation VARCHAR(64) NOT NULL DEFAULT 'cites', description TEXT, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL",
}


def upgrade():
    for name, columns in TABLES.items():
        op.execute(f"CREATE TABLE IF NOT EXISTS {name} ({columns})")
    for table in ("paper_chunks", "evidence", "notes"):
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_paper_id ON {table}(paper_id)"
        )


def downgrade():
    for table in reversed(TABLES):
        op.drop_table(table)
