from datetime import datetime, timedelta
from fastapi import Response, APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.database import get_db
from .dto import LoginRequest, Token
from .service import authenticate_admin, authenticate_user
from app.utils.generate_token import create_access_token
from app.utils.otp import (
    generate_otp,
    hash_otp,
    send_otp_email,
    save_otp_memory,
    get_otp_memory,
    delete_otp_memory,
    save_otp_verification,
)
from app.models.schema import User

router = APIRouter(prefix="/auth")


def _set_token_cookie(response: Response, token: str):
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=3600,
        samesite="lax",
        secure=False,
    )


@router.post("/login/admin", response_model=Token)
def admin_login(data: LoginRequest, response: Response, db: Session = Depends(get_db)):
    admin = authenticate_admin(db, data.email, data.password)
    if not admin:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"sub": str(admin.id), "type": "admin"})
    _set_token_cookie(response, token)
    return {"access_token": token}


@router.post("/login", response_model=Token)
def login(data: LoginRequest, response: Response, db: Session = Depends(get_db), role: str | None = None):
    user = authenticate_user(db, data.email, data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    role_names = [r.name.value if hasattr(r.name, "value") else str(r.name) for r in (user.roles or [])]
    role_names = [r.lower() for r in role_names]

    # If client requested a specific role, ensure user has it
    if role:
        role_lower = role.lower()
        if role_lower not in role_names:
            raise HTTPException(status_code=403, detail=f"User does not have role '{role}'")
        chosen_role = role_lower
    else:
        # auto-select when user has exactly one of student/teacher
        candidate_roles = [r for r in role_names if r in ("student", "teacher")]
        if len(candidate_roles) == 1:
            chosen_role = candidate_roles[0]
        elif len(candidate_roles) == 0:
            raise HTTPException(status_code=403, detail="User has no student/teacher role")
        else:
            raise HTTPException(status_code=400, detail="Multiple roles found; specify 'role' parameter")

    token = create_access_token({"userId": str(user.id), "role": chosen_role})
    _set_token_cookie(response, token)
    return {"access_token": token}


@router.post("/request-otp")
async def request_otp(email: str):
    otp = generate_otp()
    save_otp_memory(email, hash_otp(otp))

    try:
        send_otp_email(email, otp)
    except Exception:
        raise HTTPException(status_code=500, detail="Cannot send email")

    return {"message": "OTP sent to email"}


@router.post("/verify-otp")
async def verify_otp(email: str, otp: str, db: Session = Depends(get_db)):
    data = get_otp_memory(email)
    if not data:
        raise HTTPException(status_code=400, detail="OTP not found")

    if datetime.utcnow() > data["expires"]:
        delete_otp_memory(email)
        raise HTTPException(status_code=400, detail="OTP expired")

    if data["otp"] != hash_otp(otp):
        data["attempts"] = data.get("attempts", 0) + 1
        if data["attempts"] >= 5:
            delete_otp_memory(email)
        raise HTTPException(status_code=400, detail="OTP invalid")

    try:
        save_otp_verification(email)
    except Exception:
        pass

    delete_otp_memory(email)
    return {"message": "OTP verified"}

