from sqlalchemy.orm import Session
from app.core.classroommember.repository import get_classroon_member
from app.core.assignment.repository import get_assignments_by_classroom
from app.models.schema import Assignment

def get_scorebook_data(db: Session, classroom_id: int):
    # 1. Get classroom members
    members = get_classroon_member(db, classroom_id)
    # 2. Get assignments
    assignments = get_assignments_by_classroom(db, classroom_id)
    # 3. Prepare result
    result = []
    for member in members:
        student = member.student
        student_row = {
            'student_id': student.student_id,
            'name': f"{student.first_name} {student.last_name}",
            'assignments': [],
            'total_score': 0,
        }
        total_score = 0
        for assignment in assignments:
            # assignment.projects is a relationship
            score = None
            for project in assignment.projects:
                # For group assignment, check if student is in any group of this project
                if assignment.is_group:
                    found = False
                    for group in project.groups:
                        for group_member in group.members:
                            if group_member.student_id == student.id:
                                score = project.score
                                found = True
                                break
                        if found:
                            break
                else:
                    # Individual assignment: check submission_of
                    for submission in project.submission_of:
                        if submission.student_id == student.id:
                            score = project.score
                            break
            student_row['assignments'].append(score)
            if score:
                total_score += score
        student_row['total_score'] = total_score
        result.append(student_row)
    return result
