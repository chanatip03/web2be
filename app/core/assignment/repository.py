from typing import Optional, List
from datetime import datetime, timezone
from sqlalchemy.orm import Session, joinedload, with_loader_criteria
from app.models.schema import Assignment, Attachment, ProjectType, Language

def get_project_types(db: Session) -> list:
    return db.query(ProjectType).all()

def get_languages(db: Session) -> list:
    return db.query(Language).all()

def create_attachment(db: Session, attachments: List[Attachment]) -> List[Attachment]:
    db.add_all(attachments)
    db.commit()

    for attachment in attachments:
        db.refresh(attachment)

    return attachments

def update_attachment(db:Session , attachment: Attachment , update_data: dict) -> Attachment:
    for key, value in  update_data.items():
        if value is not None:
            setattr(attachment, key, value)

    db.commit()
    db.refresh(attachment)
    return attachment

def get_attachment_by_id(db:Session , attachment_id) -> Attachment:
    return  db.query(Attachment).filter(
            Attachment.id == attachment_id,
            Attachment.deleted_date == None
            ).first()

def delete_attachment_by_id(db:Session , attachment:Attachment) -> None:
    attachment.deleted_date = datetime.now(timezone.utc)
    db.commit()
    db.refresh(attachment)
    

def create_assignment(db:Session , assignment: Assignment):
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return assignment

def get_assignments_by_classroom(db: Session, classroom_id: int) -> List[Assignment]:
    return db.query(Assignment).options(
            joinedload(Assignment.project_type),
            joinedload(Assignment.language),
            joinedload(Assignment.attachments),
            with_loader_criteria(
            Attachment,
            Attachment.deleted_date.is_(None),
            include_aliases=True
                )
            ).filter(
            Assignment.classroom_id == classroom_id,
            Assignment.deleted_date.is_(None)
            ).all()


def get_assignment_by_id(db: Session, assignment_id: int) -> Assignment:
    return db.query(Assignment).options(
            joinedload(Assignment.project_type),
            joinedload(Assignment.language),
            joinedload(Assignment.attachments),
            with_loader_criteria(
            Attachment,
            Attachment.deleted_date.is_(None),
            include_aliases=True
            )
            ).filter(Assignment.id == assignment_id).first()


def update_assignment(db: Session, assignment: Assignment, update_data: dict) -> Assignment:
    for key, value in update_data.items():
        if value is not None:
            setattr(assignment, key, value)
    db.commit()
    db.refresh(assignment)
    return assignment


def soft_delete_assignment(db: Session, assignment: Assignment) -> None:
    assignment.deleted_date = datetime.now(timezone.utc)
    db.commit()
    db.refresh(assignment)