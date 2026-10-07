"""SQLite FTS5 search scoped in SQL before ranking and result limits."""
from __future__ import annotations
import re
from sqlalchemy import text
from sqlalchemy.orm import Session


def search_chunks(session: Session, query: str, limit: int = 50, *, collection_id: str | None = None, reading_status: str | None = None, is_favorite: bool | None = None) -> list[dict[str,object]]:
    terms = re.findall(r'[^\W_]+',query,re.UNICODE)
    if not terms:
        return []
    match = ' OR '.join('"' + term.replace('"','""') + '"' for term in terms)
    params: dict[str,object] = {'query':match,'limit':limit}
    filters = ''
    if collection_id is not None:
        filters += ' AND EXISTS (SELECT 1 FROM collection_papers cp WHERE cp.paper_id=c.paper_id AND cp.collection_id=:collection_id)'
        params['collection_id'] = collection_id
    if reading_status is not None:
        filters += ' AND p.reading_status=:reading_status'
        params['reading_status'] = reading_status
    if is_favorite is not None:
        filters += ' AND p.is_favorite=:is_favorite'
        params['is_favorite'] = is_favorite
    columns = 'p.id AS paper_id,p.title,c.id AS chunk_id,c.page,c.section,c.content'
    rows = session.execute(text('SELECT ' + columns + ' FROM paper_chunks_fts JOIN paper_chunks c ON c.id=paper_chunks_fts.chunk_id JOIN papers p ON p.id=c.paper_id WHERE paper_chunks_fts MATCH :query' + filters + ' ORDER BY bm25(paper_chunks_fts),c.id LIMIT :limit'),params).mappings().all()
    results = [{**dict(row),'match_type':'fts'} for row in rows]
    # CJK chunks without spaces are single unicode61 tokens. The fallback is explicit.
    if not results and re.search(r'[\u3400-\u9fff]',query):
        escaped = query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        params['query'] = f'%{escaped}%'
        rows = session.execute(text('SELECT ' + columns + " FROM paper_chunks c JOIN papers p ON p.id=c.paper_id WHERE c.content LIKE :query ESCAPE '\\'" + filters + ' ORDER BY p.id,c.page,c.id LIMIT :limit'),params).mappings().all()
        results = [{**dict(row),'match_type':'substring'} for row in rows]
    return results
