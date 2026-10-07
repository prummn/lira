"""FastAPI application factory with isolated local database and PDF storage."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.routes import router
from .db import BACKEND_DIR, DATABASE_URL, Database
from .providers.base import ProviderError


def create_app(
    database_url: str | None = None,
    storage_dir: Path | None = None,
    seed_demo: bool = True,
) -> FastAPI:
    database = Database(database_url or DATABASE_URL)
    storage = storage_dir or Path(
        os.getenv("PAPER_READER_STORAGE_DIR", str(BACKEND_DIR / "storage"))
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        database.migrate()
        storage.mkdir(parents=True, exist_ok=True)
        if seed_demo:
            from .seed import seed_database

            with database.sessions() as session:
                seed_database(session, storage)
        yield
        database.engine.dispose()

    application = FastAPI(
        title="Research Intelligence Workspace API", version="0.2.0", lifespan=lifespan
    )
    application.state.database = database
    application.state.storage_dir = storage
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(router)

    @application.exception_handler(ProviderError)
    async def provider_error(_: Request, error: ProviderError) -> JSONResponse:
        return JSONResponse(status_code=error.status_code, content={"detail": str(error)})

    @application.exception_handler(RequestValidationError)
    async def validation_error(
        _: Request, error: RequestValidationError
    ) -> JSONResponse:
        detail = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'][1:])}: {item['msg']}"
            for item in error.errors()
        )
        return JSONResponse(status_code=422, content={"detail": detail})

    return application


app = create_app()
