from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from jose import JWTError

from app.db.database import get_db
from app.utils.generate_token import decode_token
from app.models.schema import User, Admin

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
