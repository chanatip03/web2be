import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import Annotated

from app.db.database import get_db
from app.models.schema import Assignment
from app.utils.validator import get_current_user
from .scheduler import check_assignment_plagiarism

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plagiarism", tags=["Plagiarism"])


@router.post("/trigger/{assignment_id}")
async def trigger_plagiarism_check(
    assignment_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """
    Manually trigger plagiarism check for a specific assignment.
    Runs the full pipeline: download from R2 → extract → JPlag → save result.
    Only accessible by teachers. Useful for testing or re-running after a failure.
    """
    if current_user.get("role") != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can trigger plagiarism checks")

    assignment = (
        db.query(Assignment)
        .options(
            joinedload(Assignment.project_type),
            joinedload(Assignment.language),
        )
        .filter(
            Assignment.id == assignment_id,
            Assignment.deleted_date.is_(None),
        )
        .first()
    )

    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    # Reset plagiarism_result so the full pipeline runs fresh
    assignment.plagiarism_result = None
    db.commit()

    try:
        await check_assignment_plagiarism(db, assignment)
    except Exception as e:
        logger.error(f"Plagiarism trigger failed for assignment {assignment_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    db.refresh(assignment)
    return {
        "status": "success",
        "assignment_id": assignment_id,
        "total_comparisons": len(assignment.plagiarism_result) if assignment.plagiarism_result else 0,
        "data": assignment.plagiarism_result or [],
    }


@router.get("/result/{assignment_id}")
def get_plagiarism_result(
    assignment_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """
    Get the stored plagiarism result for an assignment from the database.
    """
    assignment = (
        db.query(Assignment)
        .filter(
            Assignment.id == assignment_id,
            Assignment.deleted_date.is_(None),
        )
        .first()
    )

    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    return {
        "assignment_id": assignment_id,
        "status": "checked" if assignment.plagiarism_result is not None else "pending",
        "total_comparisons": len(assignment.plagiarism_result) if assignment.plagiarism_result else 0,
        "data": assignment.plagiarism_result or [],
    }