"""Public /api router aggregates focused endpoint modules."""

from fastapi import APIRouter
from . import collections, dictionary, papers, system, model_settings

router = APIRouter(prefix="/api")
router.include_router(papers.router)
router.include_router(collections.router)
router.include_router(system.router)
router.include_router(model_settings.router)
router.include_router(dictionary.router)
