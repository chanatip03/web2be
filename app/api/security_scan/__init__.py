from fastapi import APIRouter

from app.api.security_scan.controller import router as security_router

api_router = APIRouter()

api_router.include_router(security_router)

