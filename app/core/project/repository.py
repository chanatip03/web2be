from typing import List, Optional
from sqlalchemy.orm import Session
from app.models.schema import Project, Group

def get_project_by_id(db: Session, project_id: int) -> Optional[Project]:
    return db.query(Project).filter(Project.id == project_id).first()

def get_projects_by_assignment_id(db: Session, assignment_id: int) -> List[Project]:
    return (
        db.query(Project)
        .outerjoin(Group, Project.group_id == Group.id)
        .filter(
            or_(
                Project.assignment_id == assignment_id,
                and_(
                    Project.group_id.isnot(None),
                    Group.assignment_id == assignment_id
                )
            )
        )
        .all()
    )

def update_project_grading_repo(db: Session, project: Project, score: Optional[int] = None, feedback: Optional[str] = None) -> Project:
    if score is not None:
        project.score = score
    if feedback is not None:
        project.feedback = feedback
        
    db.commit()
    db.refresh(project)
    return project
