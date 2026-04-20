from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.utils.validator import get_current_user
from .dto import ProjectResponse, ProjectUpdateGradingRequest
from .service import (
    get_project_service,
    get_projects_by_assignment_service,
    update_project_grading_service
)

#add get all

router = APIRouter(prefix="/project", tags=["Project"])

@router.get("/", response_model=List[ProjectResponse])
def get_all_projects_endpoint(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        data = get_projects_service(db, current_user)
        return data
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

@router.get("/{project_id}", response_model=ProjectResponse)
def get_project_endpoint(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        data = get_project_service(db, current_user, project_id)
        return data
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

@router.get("/assignment/{assignment_id}", response_model=List[ProjectResponse])
def get_projects_by_assignment_endpoint(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        data = get_projects_by_assignment_service(db, current_user, assignment_id)
        return data
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

@router.put("/{project_id}/grading", response_model=ProjectResponse)
def update_project_grading_endpoint(
    project_id: int,
    payload: ProjectUpdateGradingRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        data = update_project_grading_service(
            db, 
            current_user, 
            project_id, 
            background_tasks,
            score=payload.score, 
            feedback=payload.feedback
        )
        return data
    except ValueError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
