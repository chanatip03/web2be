from typing import List, Optional
from fastapi import BackgroundTasks
from sqlalchemy.orm import Session
from .repository import get_project_by_id, get_projects_by_assignment_id, update_project_grading_repo
from .dto import ProjectResponse
from app.core.assignment.repository import get_assignment_by_id
from app.core.classroom.repository import is_classroom_of_teacher
from app.core.user.repository import get_teacher_by_user_id
from app.core.submission.fs import find_latest_manifest_for_project
from app.utils.otp import send_grading_email
from app.models.schema import Project

def _to_project_response(project: Project) -> ProjectResponse:
    manifest = find_latest_manifest_for_project(project.id)
    return ProjectResponse.model_validate({
        "id": project.id,
        "group_id": project.group_id,
        "submission_type": project.submission_type,
        "project_source_url": project.project_source_url,
        "env": project.env,
        "testcase_result": project.testcase_result,
        "cybersecurity_result": project.cybersecurity_result,
        "score": project.score,
        "feedback": project.feedback,
        "submission_id": manifest.submission_id if manifest else None,
        "students": list(project.students),
    })


def get_project_service(db: Session, current_user: dict, project_id: int) -> ProjectResponse:
    project = get_project_by_id(db, project_id)
    if not project:
        raise ValueError("Project not found")
    return _to_project_response(project)

def get_projects_by_assignment_service(db: Session, current_user: dict, assignment_id: int) -> List[ProjectResponse]:
    assignment = get_assignment_by_id(db, assignment_id)
    if not assignment:
        raise ValueError("Assignment not found")
    return [_to_project_response(project) for project in get_projects_by_assignment_id(db, assignment_id)]

def update_project_grading_service(db: Session, current_user: dict, project_id: int, background_tasks: BackgroundTasks, score: Optional[int] = None, feedback: Optional[str] = None) -> Project:
    if current_user.get("role") not in ["teacher", "admin"]:
        raise ValueError("Only teachers and admins can grade projects")

    project = get_project_by_id(db, project_id)
    if not project:
        raise ValueError("Project not found")

    assignment_id = None
    if project.group_id and project.group:
        assignment_id = project.group.assignment_id
    elif project.submission_of:
        submission_of_record = project.submission_of[0] if isinstance(project.submission_of, list) and len(project.submission_of) > 0 else None
        if submission_of_record:
            assignment_id = submission_of_record.assignment_id

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

    # Email notification logic
    if assignment_id:
        assignment = get_assignment_by_id(db, assignment_id)
        if assignment:
            assignment_name = assignment.title
            target_emails = set()
            if project.group_id and project.group:
                for member in project.group.members:
                    if member.student and member.student.user:
                        target_emails.add(member.student.user.email)
            elif project.submission_of:
                # submission_of connects Project to Student, from which we can get User.email
                so_list = project.submission_of if isinstance(project.submission_of, list) else [project.submission_of]
                for so in so_list:
                    if so.student and so.student.user:
                        target_emails.add(so.student.user.email)
            
            for email in target_emails:
                background_tasks.add_task(send_grading_email, to_email=email, assignment_name=assignment_name)

    return project
