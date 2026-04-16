from datetime import datetime
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.assignment.repository import get_assignment_by_id
from app.core.classroom.repository import get_classroom_by_id
from app.core.submission.fs import read_manifest
from app.deployment.core.exceptions import DockerError
from app.deployment.services.docker.client import docker_client
from app.deployment.models.deployment import DeploymentStatus
from app.deployment.services.enhanced.health_checker import health_checker
from app.deployment.services.deployer.pipeline import deployment_store

from . import repository
from .dto import (
    AdminContainerRow,
    AdminStudentRow,
    AdminTeacherRequestRow,
    AdminTeacherRow,
)


def create_admin(db: Session, email: str, password: str):
    if repository.get_admin_by_email(db, email):
        raise HTTPException(
            status_code=400,
            detail="Admin email already exists",
        )

    return repository.create_admin(db, email, password)


def _ensure_admin(current_user: dict) -> None:
    if current_user["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can access this resource",
        )


def get_admin_students(db: Session, current_user: dict, search: str | None = None) -> list[AdminStudentRow]:
    _ensure_admin(current_user)
    users = repository.get_student_users(db, search)
    return [
        AdminStudentRow(
            id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
            academy=user.academy,
            imageUrl=user.image_url,
            studentId=user.student.student_id if user.student else None,
        )
        for user in users
    ]


def get_admin_teachers(db: Session, current_user: dict, search: str | None = None) -> list[AdminTeacherRow]:
    _ensure_admin(current_user)
    users = repository.get_teacher_users(db, search, approved_only=True)
    return [
        AdminTeacherRow(
            id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
            academy=user.academy,
            imageUrl=user.image_url,
            certificateUrl=user.teacher.certificate_url if user.teacher else None,
            isApproved=bool(user.teacher.is_approved) if user.teacher else False,
        )
        for user in users
    ]


def get_admin_teacher_requests(
    db: Session,
    current_user: dict,
    search: str | None = None,
) -> list[AdminTeacherRequestRow]:
    _ensure_admin(current_user)
    users = repository.get_teacher_users(db, search, approved_only=False)
    return [
        AdminTeacherRequestRow(
            id=user.id,
            name=f"{user.first_name} {user.last_name}",
            email=user.email,
            academy=user.academy,
            certificateUrl=user.teacher.certificate_url if user.teacher else None,
            imageUrl=user.image_url,
        )
        for user in users
    ]


def approve_teacher_request(db: Session, user_id: int, current_user: dict) -> None:
    _ensure_admin(current_user)
    user = repository.get_teacher_request_user(db, user_id)
    if not user or not user.teacher:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher request not found")

    repository.set_teacher_approval(db, user.teacher, True)


def reject_teacher_request(db: Session, user_id: int, current_user: dict) -> None:
    _ensure_admin(current_user)
    user = repository.get_teacher_request_user(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher request not found")

    repository.delete_pending_teacher_request(db, user)


def _normalize_container_status(raw_status: str | None) -> str:
    status_value = (raw_status or "").lower()
    if status_value in {"success", "running"}:
        return "running"
    if status_value in {"stopped", "exited", "dead", "removed"}:
        return "stopped"
    if status_value in {"building", "deploying", "analyzing"}:
        return status_value
    if status_value == "error":
        return "error"
    return status_value or "unknown"


def _resolve_health_target_container_id(deployment: DeploymentStatus) -> str | None:
    if deployment.container_id:
        return deployment.container_id

    compose_project = deployment.compose_project or deployment.project_id
    if not compose_project:
        return None

    try:
        containers = docker_client.client.containers.list(
            all=True,
            filters={"label": f"com.docker.compose.project={compose_project}"},
        )
    except Exception:
        return None

    if not containers:
        return None

    preferred_services = ("frontend", "backend", "app", "web")

    def container_sort_key(container) -> tuple[int, int, str]:
        labels = getattr(container, "labels", {}) or {}
        service_name = str(labels.get("com.docker.compose.service", "")).lower()
        service_rank = (
            preferred_services.index(service_name)
            if service_name in preferred_services
            else len(preferred_services)
        )
        running_rank = 0 if getattr(container, "status", "") == "running" else 1
        return (running_rank, service_rank, getattr(container, "name", ""))

    return sorted(containers, key=container_sort_key)[0].id


def _resolve_runtime_container_ids(deployment: DeploymentStatus) -> list[str]:
    compose_project = deployment.compose_project or deployment.project_id
    if compose_project:
        try:
            containers = docker_client.client.containers.list(
                filters={"label": f"com.docker.compose.project={compose_project}"},
            )
        except Exception:
            containers = []

        if containers:
            return [container.id for container in containers]

    if deployment.container_id:
        return [deployment.container_id]

    return []


async def _get_memory_usage_mb(deployment: DeploymentStatus) -> float | None:
    container_ids = _resolve_runtime_container_ids(deployment)
    if not container_ids:
        return None

    total_memory_mb = 0.0
    has_memory_usage = False

    for container_id in container_ids:
        health = await health_checker.check_container(container_id)
        resource_usage = health.get("resource_usage") or {}
        memory_usage_mb = resource_usage.get("memory_usage_mb")
        if memory_usage_mb is None:
            continue

        total_memory_mb += float(memory_usage_mb)
        has_memory_usage = True

    if not has_memory_usage:
        return None

    return round(total_memory_mb, 1)


async def get_admin_containers(db: Session, current_user: dict) -> list[AdminContainerRow]:
    _ensure_admin(current_user)

    rows: list[AdminContainerRow] = []
    deployments = sorted(
        deployment_store.list_all(),
        key=lambda deployment: deployment.updated_at,
        reverse=True,
    )
    manifests = []

    for deployment in deployments:
        try:
            manifest = read_manifest(deployment.deployment_id)
        except FileNotFoundError:
            continue
        manifests.append((deployment, manifest))

    students_by_id = repository.get_students_by_ids(
        db,
        list({manifest.student_id for _, manifest in manifests}),
    )

    for deployment, manifest in manifests:
        assignment_name = deployment.project_name or "Unknown assignment"
        teacher_name = "Unknown teacher"
        student_code = None

        assignment = get_assignment_by_id(db, manifest.assignment_id)
        if assignment:
            assignment_name = assignment.title
            classroom = get_classroom_by_id(db, assignment.classroom_id)
            if classroom and classroom.teacher and classroom.teacher.user:
                teacher_name = (
                    f"{classroom.teacher.user.first_name} {classroom.teacher.user.last_name}"
                )

        student = students_by_id.get(manifest.student_id)
        if student:
            student_code = student.student_id

        memory_usage_mb = None
        status_value = _normalize_container_status(deployment.container_state or deployment.status)
        memory_usage_mb = await _get_memory_usage_mb(deployment)
        health_target_container_id = _resolve_health_target_container_id(deployment)
        if health_target_container_id:
            health = await health_checker.check_container(health_target_container_id)
            status_value = _normalize_container_status(health.get("docker_status") or status_value)

        has_stop_target = bool(
            (deployment.compose_project and deployment.compose_file_path)
            or deployment.container_id
        )
        can_stop = has_stop_target and status_value not in {"stopped", "error", "unknown"}

        rows.append(
            AdminContainerRow(
                id=deployment.deployment_id,
                assignmentName=assignment_name,
                projectName=deployment.project_name or manifest.source_ref or "Unnamed project",
                studentId=student_code,
                teacherName=teacher_name,
                memoryUsageMB=memory_usage_mb,
                status=status_value,
                canStop=can_stop,
            )
        )

    return rows


def stop_admin_container(deployment_id: str, current_user: dict) -> None:
    _ensure_admin(current_user)
    deployment = deployment_store.get(deployment_id)
    if not deployment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")

    try:
        if deployment.compose_project and deployment.compose_file_path:
            compose_dir = str(Path(deployment.compose_file_path).parent)
            docker_client.compose_stop(compose_dir, deployment.compose_project)
        elif deployment.container_id:
            docker_client.stop_container(deployment.container_id)
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No active container to stop")
    except DockerError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    deployment.status = "stopped"
    deployment.container_state = "stopped"
    deployment.updated_at = datetime.now()
    deployment_store.save(deployment)
