from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.database import get_db
from .dto import FeedbackResponse, FeedbackNotifyRequest, FeedbackNotifyResponse
from .service import get_feedback_detail, send_feedback_notification_service

router = APIRouter(prefix="/feedback", tags=["Feedback"])


@router.post("/notify", response_model=FeedbackNotifyResponse)
def notify_feedback(payload: FeedbackNotifyRequest):
    result = send_feedback_notification_service(
        email=payload.email,
        discord_user_id=payload.discord_user_id,
        feedback_text=payload.feedback_text,
    )
    return FeedbackNotifyResponse(**result)


@router.get("/{project_id}", response_model=FeedbackResponse)
def get_feedback_endpoint(
    project_id: int,
    db: Session = Depends(get_db),
):
    user_id_mock = 2  # TODO: เปลี่ยนเป็น current_user.id

    try:
        result = get_feedback_detail(db, project_id, user_id_mock)
        return FeedbackResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch feedback: {str(e)}"
        )