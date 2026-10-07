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
            == "0004_translation_cache"
        )
        assert connection.execute(text("SELECT one_liner,findings,card_json FROM paper_analysis WHERE paper_id='legacy'")).one() == ('Preserve old analysis','Original finding','{}')
    assert "sha256" in {
        c["name"] for c in inspect(database.engine).get_columns("papers")
    }
    assert "translations" in inspect(database.engine).get_table_names()
    database.engine.dispose()
    engine.dispose()
