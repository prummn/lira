"""Request-scoped SQLite sessions and Alembic-managed schema lifecycle."""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import Request
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_PATH = BACKEND_DIR / "paper_reader.db"
DATABASE_URL = os.getenv(
    "PAPER_READER_DATABASE_URL", f"sqlite:///{DEFAULT_DATABASE_PATH.as_posix()}"
)


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        self.engine = create_engine(
            url,
            connect_args=(
                {"check_same_thread": False} if url.startswith("sqlite") else {}
            ),
        )
        if url.startswith("sqlite"):
            event.listen(self.engine, "connect", self._configure_sqlite)
        self.sessions = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False
        )

    @staticmethod
    def _configure_sqlite(connection, _) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    def migrate(self) -> None:
        config = Config(str(BACKEND_DIR / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
        config.set_main_option("sqlalchemy.url", self.url.replace("%", "%%"))
        with self.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")


def get_db(request: Request) -> Generator[Session, None, None]:
    with request.app.state.database.sessions() as session:
        yield session
