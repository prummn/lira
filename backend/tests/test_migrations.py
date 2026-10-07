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
            == "0007_intelligence"
        )
        assert connection.execute(text("SELECT one_liner,findings,card_json FROM paper_analysis WHERE paper_id='legacy'")).one() == ('Preserve old analysis','Original finding','{}')
        assert connection.execute(text("SELECT source_url,metadata_sources_json,metadata_warnings_json FROM papers WHERE id='legacy'")).one() == (None, '{}', '[]')
        assert connection.execute(text("SELECT arxiv_version FROM papers WHERE id='legacy'")).scalar() is None
    assert "sha256" in {
        c["name"] for c in inspect(database.engine).get_columns("papers")
    }
    assert "translations" in inspect(database.engine).get_table_names()
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
