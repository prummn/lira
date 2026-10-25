from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.db import BACKEND_DIR, Database


def test_unversioned_legacy_database_upgrades_without_losing_notes(
    tmp_path: Path,
) -> None:
    url = f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}"
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "0001_baseline")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO papers(id,title,reading_status,is_favorite,analysis_status,tags_json,created_at,updated_at) VALUES('legacy','Kept paper','reading',0,'ready','[]',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(text("INSERT INTO paper_analysis(paper_id,one_liner,findings,concepts_json) VALUES('legacy','Preserve old analysis','Original finding','[]')"))
        connection.execute(
            text(
                "INSERT INTO notes(id,paper_id,content,created_at,updated_at) VALUES('old-note','legacy','My real thought',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(text("DROP TABLE alembic_version"))
    database = Database(url)
    database.migrate()
    database.migrate()
    with database.engine.connect() as connection:
        assert connection.execute(
            text("SELECT content,kind FROM notes WHERE id='old-note'")
        ).one() == ("My real thought", "note")
        assert connection.execute(
            text("SELECT page_count,is_demo FROM papers WHERE id='legacy'")
        ).one() == (0, 0)
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
                == "0015_knowledge_maintenance"
        )
        assert connection.execute(text("SELECT one_liner,findings,card_json FROM paper_analysis WHERE paper_id='legacy'")).one() == ('Preserve old analysis','Original finding','{}')
        assert connection.execute(text("SELECT source_url,metadata_sources_json,metadata_warnings_json FROM papers WHERE id='legacy'")).one() == (None, '{}', '[]')
        assert connection.execute(text("SELECT arxiv_version FROM papers WHERE id='legacy'")).scalar() is None
    assert "sha256" in {
        c["name"] for c in inspect(database.engine).get_columns("papers")
    }
    assert "translations" in inspect(database.engine).get_table_names()
    with database.engine.connect() as connection:
        assert connection.execute(text("SELECT anchors_json FROM notes WHERE id='old-note'")).scalar() == '[]'
    database.engine.dispose()
    engine.dispose()


def test_intelligence_migration_distinguishes_old_remote_and_local_cards(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'old-cards.db').as_posix()}"
    config = Config(str(BACKEND_DIR / 'alembic.ini'))
    config.set_main_option('script_location', str(BACKEND_DIR / 'migrations'))
    config.set_main_option('sqlalchemy.url', url)
    command.upgrade(config, '0006_arxiv_revision')
    engine = create_engine(url)
    with engine.begin() as connection:
        for paper_id, mode in [('local', 'extractive'), ('remote', 'remote')]:
            connection.execute(text("INSERT INTO papers(id,title,reading_status,is_favorite,analysis_status,tags_json,created_at,updated_at) VALUES(:id,'Original title','reading',0,'ready','[]',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"), {'id': paper_id})
            connection.execute(text("INSERT INTO paper_analysis(paper_id,one_liner,concepts_json,provider,mode) VALUES(:id,'Preserved card','[]','OriginalProvider',:mode)"), {'id': paper_id, 'mode': mode})
    database = Database(url)
    database.migrate()
    with database.engine.connect() as connection:
        rows = dict(connection.execute(text('SELECT id,intelligence_status FROM papers')).all())
        assert rows == {'local': 'unanalyzed', 'remote': 'partial'}
        assert connection.execute(text("SELECT title,reading_status FROM papers WHERE id='remote'")).one() == ('Original title', 'reading')
        assert connection.execute(text("SELECT one_liner,mode FROM paper_analysis WHERE paper_id='remote'")).one() == ('Preserved card', 'remote')
        assert 'run_token' in {column['name'] for column in inspect(connection).get_columns('intelligence_tasks')}
    database.engine.dispose()
    engine.dispose()


def test_curation_upgrade_preserves_confirmations_quotes_and_foreign_keys(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'curation.db').as_posix()}"
    config = Config(str(BACKEND_DIR / 'alembic.ini'))
    config.set_main_option('script_location', str(BACKEND_DIR / 'migrations'))
    config.set_main_option('sqlalchemy.url', url)
    command.upgrade(config, '0011_conversations')
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO papers(id,title,reading_status,is_favorite,analysis_status,tags_json,created_at,updated_at) VALUES('p','Kept paper','reading',0,'ready','[]',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO knowledge_entities(id,entity_type,name,normalized_name,aliases_json,status,created_at,updated_at) VALUES('e','method','ReAct','react','[]','active',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO knowledge_candidates(id,paper_id,entity_id,entity_type,name,normalized_name,role,confidence,status,evidence_json,created_at,updated_at) VALUES('c','p','e','method','ReAct','react','used',0.9,'confirmed','[{\"chunk_id\":\"source\",\"quote\":\"Original quote\"}]',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
    database = Database(url)
    database.migrate()
    with database.engine.connect() as connection:
        assert connection.execute(text("SELECT name,links_json,merged_into_id FROM knowledge_entities WHERE id='e'")).one() == ('ReAct','[]',None)
        assert connection.execute(text("SELECT entity_id,status,evidence_json FROM knowledge_candidates WHERE id='c'")).one() == ('e','confirmed','[{"chunk_id":"source","quote":"Original quote"}]')
        assert connection.execute(text('PRAGMA foreign_key_check')).all() == []
        assert connection.execute(text('SELECT COUNT(*) FROM knowledge_changes')).scalar() == 0
    database.engine.dispose()
    engine.dispose()
def test_research_findings_upgrade_keeps_existing_scopes_and_tasks(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'research.db').as_posix()}"
    config = Config(str(BACKEND_DIR / 'alembic.ini'))
    config.set_main_option('script_location', str(BACKEND_DIR / 'migrations'))
    config.set_main_option('sqlalchemy.url', url)
    command.upgrade(config, '0013_background_research')
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO collections(id,name,color,created_at,updated_at) VALUES('topic','Memory','#aaa',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO research_scopes(collection_id,enabled,focus,created_at,updated_at) VALUES('topic',1,'Kept focus',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO research_tasks(id,collection_id,fingerprint,status,stage,material_json,checkpoint_json,attempts,calls,usage_json,created_at,updated_at) VALUES('job','topic','abc','completed','published','{}','{}',0,3,'{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
    database = Database(url)
    database.migrate()
    with database.engine.connect() as connection:
        assert connection.execute(text('SELECT kind,status FROM research_tasks')).one() == ('essay', 'completed')
        assert connection.execute(text('SELECT focus,work_types_json FROM research_scopes')).one() == ('Kept focus', '["essay"]')
        assert connection.execute(text('PRAGMA foreign_key_check')).all() == []
    assert 'research_finding_revisions' in inspect(database.engine).get_table_names()
    database.engine.dispose()
    engine.dispose()


def test_knowledge_maintenance_upgrade_adds_persistent_runs_and_issues(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'maintenance.db').as_posix()}"
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "0014_research_findings")
    database = Database(url)
    database.migrate()
    with database.engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert {"knowledge_maintenance_runs", "knowledge_maintenance_issues"} <= tables
        connection.execute(text(
            "INSERT INTO knowledge_maintenance_runs "
            "(id,scope_type,status,source_fingerprint,created_at,updated_at) "
            "VALUES('run-1','library','complete','fp',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
        ))
        connection.commit()
        connection.execute(text(
            "INSERT INTO knowledge_maintenance_issues "
            "(id,run_id,kind,severity,status,confidence,summary,reasoning,source_fingerprint,created_at,updated_at) "
            "VALUES('issue-1','run-1','identity','warning','proposed',0.9,'Duplicate','Evidence','fp',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
        ))
        connection.commit()
        assert connection.execute(text("SELECT run_id,status FROM knowledge_maintenance_issues")).one() == ("run-1", "proposed")
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    database.engine.dispose()
