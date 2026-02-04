from fastapi import APIRouter
from app.core.auth.controller import router as auth_router
from app.core.admin.controller import router as admin_router
from app.core.plagiarism.controller import router as plagiarism_router
from app.core.student.controller import router as student_router
from app.core.teacher.controller import router as teacher_router
from app.core.security_scan import security_router
from app.core.classroom.controller import router as classroom_router

api_router = APIRouter()

api_router.include_router(auth_router)
api_router.include_router(admin_router)
api_router.include_router(plagiarism_router)
api_router.include_router(student_router)
api_router.include_router(teacher_router)
api_router.include_router(security_router)
api_router.include_router(classroom_router)
