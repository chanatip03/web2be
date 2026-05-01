from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.utils.validator import get_current_user

from .dto import (
    AdminContainerRow,
    AdminStudentRow,
    AdminTeacherRequestRow,
    AdminTeacherRow,
    CreateAdminRequest,
)
from .service import (
    approve_teacher_request,
    create_admin,
    get_admin_containers,
    get_admin_students,
    get_admin_teacher_requests,
    get_admin_teachers,
    reject_teacher_request,
    stop_admin_container,
)

router = APIRouter(prefix="/admin")

@router.post("/")
def create_admin_user(
    data: CreateAdminRequest,
    db: Session = Depends(get_db),
):
    admin = create_admin(db, data.email, data.password)
    return {"id": admin.id, "email": admin.email}


@router.get("/students", response_model=list[AdminStudentRow])
def get_admin_students_endpoint(
    search: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return get_admin_students(db, current_user, search)


@router.get("/teachers", response_model=list[AdminTeacherRow])
def get_admin_teachers_endpoint(
    search: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return get_admin_teachers(db, current_user, search)


@router.get("/teacher-requests", response_model=list[AdminTeacherRequestRow])
def get_admin_teacher_requests_endpoint(
    search: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return get_admin_teacher_requests(db, current_user, search)


@router.post("/teacher-requests/{user_id}/approve")
def approve_teacher_request_endpoint(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    approve_teacher_request(db, user_id, current_user)
    return {"message": "Teacher approved"}


@router.post("/teacher-requests/{user_id}/reject")
def reject_teacher_request_endpoint(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    reject_teacher_request(db, user_id, current_user)
    return {"message": "Teacher request rejected"}


@router.get("/containers", response_model=list[AdminContainerRow])
async def get_admin_containers_endpoint(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await get_admin_containers(db, current_user)


@router.post("/containers/{deployment_id}/stop")
def stop_admin_container_endpoint(
    deployment_id: str,
    current_user: dict = Depends(get_current_user),
):
    stop_admin_container(deployment_id, current_user)
    return {"message": "Container stopped"}
