from fastapi import APIRouter

from . import (
    ai_boundary,
    audit_log,
    cases,
    demands,
    documents,
    facts,
    jobs,
    medical,
    revisions,
    templates,
)

router = APIRouter(prefix="/v1")
router.include_router(cases.router)
router.include_router(medical.router)
router.include_router(documents.router)
router.include_router(templates.router)
router.include_router(facts.router)
router.include_router(demands.router)
router.include_router(revisions.router)
router.include_router(jobs.router)
router.include_router(audit_log.router)
router.include_router(ai_boundary.router)

__all__ = ["router"]
