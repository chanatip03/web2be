from datetime import datetime, timezone
from fastapi import Request, Response, APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import get_db
from .dto import LoginRequest, Token
from .service import authenticate_admin, authenticate_user
from app.utils.generate_token import create_access_token , decode_token
from app.utils.otp import (
    generate_otp,
    hash_otp,
    send_otp_email,
    save_otp_memory,
    get_otp_memory,
    delete_otp_memory,
    save_otp_verification,
    )

router = APIRouter(prefix="/auth" , tags=["auth"])


def _set_token_cookie(response: Response, token: str):
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=3600,
        samesite="lax",
        secure=False,
    )


@router.post("/login-admin", response_model=Token)
def admin_login(data: LoginRequest, response: Response, db: Session = Depends(get_db)):
    admin = authenticate_admin(db, data.email, data.password)
    if not admin:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"sub": str(admin.id), "type": "admin"})
    _set_token_cookie(response, token)
    return {"access_token": token}


@router.post("/login", response_model=Token)
def login(data: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = authenticate_user(db, data.email, data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.roles or len(user.roles) != 1:
        raise HTTPException(
            status_code=500,
            detail="User must have exactly one role"
        )

    role = user.roles[0].name
    role_name = role.value if hasattr(role, "value") else str(role)
    role_name = role_name.lower()

    token = create_access_token({"userId": str(user.id), "role": role_name})
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
async def verify_otp(email: str, otp: str):
    data = get_otp_memory(email)
    if not data:
        raise HTTPException(status_code=400, detail="OTP not found")

    if  datetime.now(timezone.utc) > data["expires"]:
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

@router.post("/check-user-token")
async def check_user_token(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="No access token")
    
    try:
        payload = decode_token(token)
        return payload
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid token")


