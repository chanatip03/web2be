from sqlalchemy.orm import Session
from .repository import (get_classroom_for_syllabus, get_classroom_if_teacher, get_students_query, 
                         count_students, get_classroom_if_teacher, get_teacher_by_user_id, get_classroom_for_syllabus)
from app.models.schema import LearningOutcome

def get_syllabus_data(db: Session, classroom_id: int, user_id: int):
    teacher = get_teacher_by_user_id(db, user_id)
    if not teacher:
        return None

    classroom = get_classroom_for_syllabus(db, classroom_id, teacher.id)
    if not classroom:
        return None

    teacher_name = f"{classroom.teacher.user.first_name} {classroom.teacher.user.last_name}"

    return {
        "classroom_name": classroom.name,
        "teacher_name": teacher_name,
        "classroom_description": classroom.description,
        "learning_outcomes": classroom.learning_outcomes
    }

def update_classroom_data(db: Session, classroom_id: int, user_id: int, payload):
    teacher = get_teacher_by_user_id(db, user_id)
    if not teacher:
        return False

    classroom = get_classroom_if_teacher(db, classroom_id, teacher.id)
    if not classroom:
        return False

    if payload.name is not None:
        classroom.name = payload.name

    if payload.description is not None:
        classroom.description = payload.description

    if payload.learning_outcomes is not None:
        keep_ids = []

        for lo in payload.learning_outcomes:
            if lo.id:
                existing = next((x for x in classroom.learning_outcomes if x.id == lo.id), None)
                if existing:
                    existing.description = lo.description
                    keep_ids.append(existing.id)
            else:
                new_lo = LearningOutcome(classroom_id=classroom.id, description=lo.description)
                db.add(new_lo)

        for old_lo in classroom.learning_outcomes:
            if old_lo.id not in keep_ids:
                db.delete(old_lo)

    db.commit()
    return True