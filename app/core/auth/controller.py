from datetime import datetime, timezone
from typing import Optional
import uuid
from fastapi import File, Form, Response, APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.models.schema import User
from app.utils.r2 import upload_file
from app.utils.validator import get_current_user
from .dto import (
    LoginRequest, MeResponse, Token, VerifyOtpRequest, register_request,
    ForgotPasswordRequest, ResetPasswordRequest,
)
from .service import authenticate_admin, authenticate_user, get_user_data_service, reset_user_password_service
from .repository import get_user_by_email
from app.utils.generate_token import create_access_token
from app.utils.otp import (
    generate_otp,
    hash_otp,
    send_otp_email,
    save_otp_memory,
    get_otp_memory,
    delete_otp_memory,
)
from app.core.user.service import create_user_service

router = APIRouter(prefix="/auth", tags=["auth"])

def _set_token_cookie(response: Response, token: str):
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=3600,
        samesite="lax",
        secure=False,
        path="/",
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
async def request_otp(
    data: register_request = Depends(register_request.as_form),
    student_id: Optional[str] = Form(None),
    certificate: Optional[UploadFile] = File(None),
):
    otp = generate_otp()

    if data.role == "student":
        data.student_id = student_id

    if data.role == "teacher":
        if not certificate:
            raise HTTPException(400, "Certificate required")

        content = await certificate.read()
        key = f"certificates/{uuid.uuid4()}.{certificate.filename.split('.')[-1]}"
        _, url = upload_file(key, content, content_type=certificate.content_type)

        data.certificate_url = url

    save_otp_memory(
    email=data.email,
    otp_hash=hash_otp(otp),
    payload={
        "role": data.role,
        "data": data.model_dump(),
    }
)
    print("SAVE OTP FOR:", data.email)

    send_otp_email(data.email, otp)
    return {"message": "OTP sent"}


@router.post("/verify-otp")
def verify_otp(data: VerifyOtpRequest, db: Session = Depends(get_db)):
    email = data.email
    otp = data.otp

    record = get_otp_memory(email)
    if not record:
        raise HTTPException(status_code=400, detail="OTP not found")

    if datetime.now(timezone.utc) > record["expires"]:
        delete_otp_memory(email)
        raise HTTPException(status_code=400, detail="OTP expired")

    if record["otp"] != hash_otp(otp):
        record["attempts"] = record.get("attempts", 0) + 1
        if record["attempts"] >= 5:
            delete_otp_memory(email)
        raise HTTPException(status_code=400, detail="OTP invalid")

    print("SAVE OTP FOR:", email)

    payload = record["payload"]
    role = payload["role"]
    data = payload["data"]

    if isinstance(data, dict) is False:
        data = data.model_dump()

    try:
        if role == "student":
            create_user_service(
                db,
                role,
                data["first_name"],
                data["last_name"],
                data["email"],
                data["password"],
                data.get("academy"),
                student_id=data.get("student_id"),
            )

        elif role == "teacher":
                create_user_service(
                    db,
                    role,
                    data["first_name"],
                    data["last_name"],
                    data["email"],
                    data["password"],
                    data["academy"],
                    data["certificate_url"],
                )
        else:
            raise HTTPException(status_code=400, detail="Invalid role")

    finally:
        delete_otp_memory(email)

    return {
        "message": "Register success",
    }


@router.post("/forgot-password")
def forgot_password(data: ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = get_user_by_email(db, data.email)
    # ไม่เปิดเผยว่า email มีในระบบหรือไม่ (prevent user enumeration)
    if not user:
        return {"message": "If this email exists, an OTP has been sent"}

    otp = generate_otp()
    save_otp_memory(
        email=data.email,
        otp_hash=hash_otp(otp),
        payload={"purpose": "reset_password", "user_id": user.id},
    )
    send_otp_email(data.email, otp)
    return {"message": "If this email exists, an OTP has been sent"}


@router.post("/reset-password")
def reset_password(data: ResetPasswordRequest, db: Session = Depends(get_db)):
    record = get_otp_memory(data.email)
    if not record:
        raise HTTPException(status_code=400, detail="OTP not found")

    if datetime.now(timezone.utc) > record["expires"]:
        delete_otp_memory(data.email)
        raise HTTPException(status_code=400, detail="OTP expired")

    if record["otp"] != hash_otp(data.otp):
        record["attempts"] = record.get("attempts", 0) + 1
        if record["attempts"] >= 5:
            delete_otp_memory(data.email)
        raise HTTPException(status_code=400, detail="OTP invalid")

    payload = record["payload"]
    if payload.get("purpose") != "reset_password":
        raise HTTPException(status_code=400, detail="Invalid OTP purpose")

    reset_user_password_service(db, payload["user_id"], data.new_password)
    delete_otp_memory(data.email)

    return {"message": "Password reset successful"}


@router.get("/me", response_model=MeResponse)
async def get_user_data(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user = get_user_data_service(db, current_user["id"])
    return map_user_to_me_response(user)


def map_user_to_me_response(user: User):
    return {
        "user": user,
        "roles": user.roles,
        "student": user.student,
        "teacher": user.teacher,
    }