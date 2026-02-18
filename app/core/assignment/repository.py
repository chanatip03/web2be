from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.schema import Assignment, Attachment, Classroom, ProjectType, Language


def get_classroom_by_id(db: Session, classroom_id: int) -> Optional[Classroom]:
    return db.query(Classroom).filter(
        Classroom.id == classroom_id,
        Classroom.deleted_date.is_(None)
    ).first()


def get_project_type_by_id(db: Session, project_type_id: int) -> Optional[ProjectType]:
    return db.query(ProjectType).filter(ProjectType.id == project_type_id).first()


def get_language_by_id(db: Session, language_id: int) -> Optional[Language]:
    return db.query(Language).filter(Language.id == language_id).first()


def get_all_project_types(db: Session) -> list:
    return db.query(ProjectType).all()


def get_all_languages(db: Session) -> list:
    return db.query(Language).all()


def create_assignment(
    db: Session,
    classroom_id: int,
    title: str,
    description: Optional[str],
    start_date: datetime,
    due_date: datetime,
    is_group: bool,
    is_public: bool,
    project_type_id: int,
    language_id: int,
    testcase_url: Optional[str],
) -> Assignment:
    assignment = Assignment(
        classroom_id=classroom_id,
        title=title,
        description=description,
        start_date=start_date,
        due_date=due_date,
        is_group=is_group,
        is_public=is_public,
        project_type_id=project_type_id,
        language_id=language_id,
        testcase_url=testcase_url,
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return assignment


def create_attachment(db: Session, assignment_id: int, file_url: str) -> Attachment:
    attachment = Attachment(
        assignment_id=assignment_id,
        file_url=file_url,
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return attachment


def get_assignments_by_classroom(db: Session, classroom_id: int) -> List[Assignment]:
    return db.query(Assignment).filter(
        Assignment.classroom_id == classroom_id,
        Assignment.deleted_date.is_(None)
    ).all()


def get_assignment_by_id(db: Session, assignment_id: int) -> Optional[Assignment]:
    return db.query(Assignment).filter(
        Assignment.id == assignment_id,
        Assignment.deleted_date.is_(None)
    ).first()


def update_assignment(db: Session, assignment: Assignment, update_data: dict) -> Assignment:
    for key, value in update_data.items():
        if value is not None:
            setattr(assignment, key, value)
    db.commit()
    db.refresh(assignment)
    return assignment


def soft_delete_assignment(db: Session, assignment: Assignment) -> None:
    from datetime import timezone
    assignment.deleted_date = datetime.now(timezone.utc)
    db.commit()