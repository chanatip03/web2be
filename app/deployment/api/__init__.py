from fastapi import APIRouter

from app.deployment.api.deploy import router as deploy_router
from app.deployment.api.projects import router as projects_router
from app.deployment.api.deployments import router as deployments_router
from app.deployment.api.health import router as health_router
from app.deployment.api.enhanced import router as enhanced_router
from app.deployment.api.submission_preview import router as submission_preview_router
from app.deployment.api.preview import router as preview_router


router = APIRouter()

router.include_router(deploy_router)
router.include_router(projects_router)
router.include_router(deployments_router)
router.include_router(health_router)
router.include_router(enhanced_router)
# submission_preview MUST come before preview_router.
# preview.py has a greedy /api/{path:path} catch-all that would swallow
# /api/project/{id}/preview/* if registered first.
router.include_router(submission_preview_router)
router.include_router(preview_router)