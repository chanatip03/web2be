from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.database import get_db
from .dto import UpsertScorebookRequest, ScorebookResponse
from .service import get_scorebook_detail, save_scorebook
# from app.auth.dependencies import get_current_user

router = APIRouter(prefix="/scorebook", tags=["Scorebook"])


@router.get("/{project_id}", response_model=ScorebookResponse)
def get_scorebook_endpoint(
    project_id: int,
    db: Session = Depends(get_db),
    # current_user: User = Depends(get_current_user)  # TODO: เพิ่ม auth
):

    # TODO: ใช้ current_user.id แทน user_id_mock
    user_id_mock = 1

    try:
        result = get_scorebook_detail(db, project_id, user_id_mock)
        return ScorebookResponse(**result)
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
            detail=f"Failed to fetch scorebook: {str(e)}"
        )


@router.put("/{project_id}", response_model=ScorebookResponse)
def upsert_scorebook_endpoint(
    project_id: int,
    data: UpsertScorebookRequest,
    db: Session = Depends(get_db),
    # current_user: User = Depends(get_current_user)  # TODO: เพิ่ม auth
):
   
    # TODO: ใช้ current_user.id แทน user_id_mock
    user_id_mock = 1

    try:
        result = save_scorebook(
            db=db,
            project_id=project_id,
            user_id=user_id_mock,
            score=data.score,
            feedback=data.feedback,
        )
        return ScorebookResponse(**result)
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
            detail=f"Failed to save scorebook: {str(e)}"
        )