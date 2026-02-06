from sqlalchemy.orm import Session
from .repository import (get_classroom_for_syllabus, get_classroom_if_teacher, get_students_query, 
                         count_students, get_classroom_if_teacher, get_teacher_by_user_id, get_classroom_for_syllabus)
from app.models.schema import LearningOutcome

def get_classroom_students(db, classroom_id: int, user_id: int, search: str | None):
    teacher = get_teacher_by_user_id(db, user_id)
    if not teacher:
        return None

    classroom = get_classroom_if_teacher(db, classroom_id, teacher.id)
    if not classroom:
        return None

    student_objs = get_students_query(db, classroom_id, search).all()
    total = count_students(db, classroom_id)

    students = []
    for s in student_objs:
        students.append({
            "id": s.id,
            "first_name": s.user.first_name,
            "last_name": s.user.last_name,
            "email": s.user.email,
            "student_id": s.student_id,
            "image_url": s.user.image_url
        })

    return {
        "total_students": total,
        "students": students
    }