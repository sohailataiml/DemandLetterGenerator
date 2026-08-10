from fastapi import APIRouter

from . import audit_log, cases, demands, documents, facts, medical

router = APIRouter(prefix="/v1")
router.include_router(cases.router)
router.include_router(medical.router)
router.include_router(documents.router)
router.include_router(facts.router)
router.include_router(demands.router)
router.include_router(audit_log.router)

__all__ = ["router"]
