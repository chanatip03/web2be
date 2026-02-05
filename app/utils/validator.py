from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from jose import JWTError

from app.db.database import get_db
from app.utils.generate_token import decode_token
from app.models.schema import User, Admin, Teacher

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_actor(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    try:
        payload = decode_token(token)
        actor_id = payload.get("userId") or payload.get("sub")
        actor_type = payload.get("role") or payload.get("type")

        if not actor_id or not actor_type:
            raise HTTPException(status_code=401, detail="Invalid token")

    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    if actor_type == "admin":
        actor = db.query(Admin).filter(Admin.id == int(actor_id)).first()
    elif actor_type in ("user", "student", "teacher"):
        actor = db.query(User).filter(User.id == int(actor_id)).first()
    else:
        raise HTTPException(status_code=401, detail="Invalid token type")

    if not actor:
        raise HTTPException(status_code=401, detail="User not found")

    return actor

def get_current_teacher(
    actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> Teacher:
    """
    ใช้สำหรับ route ที่อนุญาตเฉพาะครูเท่านั้น
    รองรับ token ที่ role เป็น "teacher" หรือ user ที่มี teacher profile
    """

    # กรณี token บอกว่าเป็น teacher โดยตรง
    if isinstance(actor, User) and actor.teacher:
        teacher = db.query(Teacher).filter(
            Teacher.user_id == actor.id,
            Teacher.deleted_date.is_(None)
        ).first()

        if not teacher:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Teacher profile not found"
            )

        return teacher

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Only teachers can perform this action"
    )