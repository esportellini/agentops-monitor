from fastapi import APIRouter
from app.api.v1 import (
    agents, api_keys, audit_logs, auth, environments, evaluations,
    health, metrics, organizations, privacy, projects, security, traces,
)

router = APIRouter()
router.include_router(health.router, tags=["health"])
router.include_router(auth.router)
router.include_router(organizations.router)
router.include_router(projects.router)
router.include_router(agents.router)
router.include_router(environments.router)
router.include_router(api_keys.router)
router.include_router(traces.router)
router.include_router(metrics.router)
router.include_router(security.router)
router.include_router(evaluations.router)
router.include_router(privacy.router)
router.include_router(audit_logs.router)
