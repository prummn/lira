"""Public /api router aggregates focused endpoint modules."""

from fastapi import APIRouter
from . import activity, collections, conversations, dictionary, papers, system, model_settings, knowledge, knowledge_maintenance, research

router = APIRouter(prefix="/api")
router.include_router(papers.router)
router.include_router(collections.router)
router.include_router(system.router)
router.include_router(model_settings.router)
router.include_router(dictionary.router)
router.include_router(activity.router)
router.include_router(knowledge.router)
router.include_router(knowledge_maintenance.router)
router.include_router(conversations.router)
router.include_router(research.router)
