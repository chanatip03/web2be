from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from jose import JWTError

from app.db.database import get_db
from app.utils.generate_token import decode_token
from app.models.schema import User, Admin


def get_current_user(
    request: Request,
    db: Session = Depends(get_db)
):
    token = request.cookies.get("access_token")

    if not token:
        raise HTTPException(status_code=401, detail="No access token")

    try:
        payload = decode_token(token)
        user_id = payload.get("userId") or payload.get("sub")
        user_role = payload.get("role")

        if not user_role and payload.get("type") == "admin":
            user_role = "admin"

        if not user_id or not user_role:
            raise HTTPException(status_code=401, detail="Invalid token")

    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    if user_role == "admin":
        user = db.query(Admin).filter(Admin.id == int(user_id)).first()
    elif user_role in ("student", "teacher"):
        user = db.query(User).filter(
            (User.id == int(user_id)) &
            (User.deleted_date.is_(None)
)
        ).first()
    else:
        raise HTTPException(status_code=401, detail="Invalid token type")

    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    if user_role == "teacher":
        teacher = getattr(user, "teacher", None)
        if not teacher or not bool(teacher.is_approved):
            raise HTTPException(status_code=403, detail="Teacher account is pending admin approval")

    return {
    "id": user.id,
    "role": user_role
}
