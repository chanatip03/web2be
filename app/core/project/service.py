from typing import List, Optional
from fastapi import BackgroundTasks
from sqlalchemy.orm import Session
from .repository import get_project_by_id, get_projects_by_assignment_id, update_project_grading_repo
from app.core.assignment.repository import get_assignment_by_id
from app.core.classroom.repository import is_classroom_of_teacher
from app.core.user.repository import get_teacher_by_user_id
from app.utils.otp import send_grading_email
from app.models.schema import Project

def get_project_service(db: Session, current_user: dict, project_id: int) -> Project:
    project = get_project_by_id(db, project_id)
    if not project:
        raise ValueError("Project not found")
    return project

def get_projects_by_assignment_service(db: Session, current_user: dict, assignment_id: int) -> List[Project]:
    assignment = get_assignment_by_id(db, assignment_id)
    if not assignment:
        raise ValueError("Assignment not found")
    return get_projects_by_assignment_id(db, assignment_id)

def update_project_grading_service(db: Session, current_user: dict, project_id: int, background_tasks: BackgroundTasks, score: Optional[int] = None, feedback: Optional[str] = None) -> Project:
    if current_user.get("role") not in ["teacher", "admin"]:
        raise ValueError("Only teachers and admins can grade projects")

    project = get_project_by_id(db, project_id)
    if not project:
        raise ValueError("Project not found")

    assignment_id = None
    if project.group_id and project.group:
        assignment_id = project.group.assignment_id

    if current_user.get("role") == "teacher":
        teacher = get_teacher_by_user_id(db, current_user["id"])
        if not teacher:
            raise ValueError("Teacher profile not found")

        if not assignment_id:
            raise ValueError("Project is not linked to any assignment")

        assignment = get_assignment_by_id(db, assignment_id)
        if not assignment or not is_classroom_of_teacher(db, assignment.classroom_id, teacher.id):
            raise ValueError("Access denied to grade this project")

    project = update_project_grading_repo(db, project, score, feedback)

    if assignment_id:
        assignment = get_assignment_by_id(db, assignment_id)
        if assignment:
            assignment_name = assignment.title
            target_emails = set()
            if project.group_id and project.group:
                for member in project.group.members:
                    if member.student and member.student.user:
                        target_emails.add(member.student.user.email)
            
            for email in target_emails:
                background_tasks.add_task(send_grading_email, to_email=email, assignment_name=assignment_name)

    return project
