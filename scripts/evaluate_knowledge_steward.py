"""Serial, opt-in real-account evaluation against an isolated SQLite backup."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from sqlalchemy import select
from app.db import Database
from app.models import CollectionPaper, Paper
from app.providers.profiles import ProfileStore
from app.providers.base import ProviderError
from app.services.knowledge_steward import build_bundle, apply_batch
from app.services.publication_metadata import enrich_publication
from app.services.research_policy import quota_decision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collection', required=True)
    parser.add_argument('--papers', nargs='*')
    parser.add_argument('--limit', type=int, default=3)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    target = args.output.resolve()
    target.mkdir(parents=True, exist_ok=True)
    database_path = target / 'evaluation.db'
    if database_path.exists():
        raise SystemExit('Use a new output directory; previous evaluation is preserved.')
    with sqlite3.connect((ROOT / 'backend/paper_reader.db').as_uri() + '?mode=ro', uri=True) as source:
        with sqlite3.connect(database_path) as destination:
            source.backup(destination)
    database = Database('sqlite:///' + database_path.as_posix())
    profiles = ProfileStore(ROOT / '.env.models.json')
    profile = next(p for p in profiles.public()['profiles'] if p.get('provider_kind') == 'codex')
    provider = profiles.subscription_provider(profile['id'])
    results = []
    with database.sessions() as db:
        ids = list(db.scalars(select(CollectionPaper.paper_id).where(CollectionPaper.collection_id == args.collection)))
    if args.papers:
        ids = [p for p in args.papers if p in ids]
    try:
        for identifier in ids[:args.limit]:
            # This is explicitly requested evaluation, never automatic quota
            # consumption. Even here preserve the configured official reserves.
            state = profiles.codex.status(refresh=True)
            gate = quota_decision(state.get('limits', []), age=0)
            if not state.get('authenticated') or not gate['allowed']:
                print(json.dumps({'stopped': gate['reason']}), flush=True)
                break
            with database.sessions() as db:
                paper = db.get(Paper, identifier)
                publication = enrich_publication(db, paper, allow_external=True)
                bundle = build_bundle(db, paper)
                db.commit()
                (target / (identifier + '-input.json')).write_text(json.dumps(bundle, ensure_ascii=False), encoding='utf-8')
                print(json.dumps({'started': identifier, 'source_chars': bundle['source_chars'], 'coverage': bundle['coverage']}), flush=True)
                started = time.monotonic()
                try:
                    response = provider.audit_knowledge_bundle(bundle)
                    (target / (identifier + '-response.json')).write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding='utf-8')
                    db.expire_all()
                    report = apply_batch(db, paper, response, bundle)
                    db.commit()
                except ProviderError as error:
                    db.rollback()
                    report = {'paper_id': identifier, 'error': str(error), 'code': error.code}
                report.update(publication=publication, seconds=round(time.monotonic()-started, 1), usage=provider.last_usage)
                results.append(report)
                (target / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps({k:v for k,v in report.items() if k not in {'change_ids','publication','usage','summary'}}, ensure_ascii=True), flush=True)
    finally:
        profiles.codex.close()
        database.engine.dispose()


if __name__ == '__main__':
    main()
