from datetime import datetime, timezone
from typing import Optional
from urllib import response
from typing_extensions import Annotated
import uuid
from fastapi import File, Response, APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.models.schema import User
from app.utils.r2 import upload_file
from app.utils.validator import get_current_user
from .dto import LoginRequest, MeResponse, Token, VerifyOtpRequest, register_request
from .service import authenticate_admin, authenticate_user, get_user_data_service
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

router = APIRouter(prefix="/auth" , tags=["auth"])

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

    if not user.role:
        raise HTTPException(
            status_code=500,
            detail="User has no role assigned"
        )

    role_name = user.role.name.value if hasattr(user.role.name, "value") else str(user.role.name)
    role_name = role_name.lower()

    token = create_access_token({"userId": str(user.id), "role": role_name})
    _set_token_cookie(response, token)
    return {"access_token": token}


@router.post("/request-otp")
async def request_otp(
    data: register_request = Depends(register_request.as_form),
    certificate: Optional[UploadFile] = File(None),
):
    otp = generate_otp()

    # role_id 1 = student, role_id 2 = teacher
    if data.role_id == 2:
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
            "role_id": data.role_id,
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

    payload = record["payload"]
    role_id: int = payload["role_id"]
    user_data: dict = payload["data"]

    try:
        create_user_service(
            db,
            role_id,
            user_data["first_name"],
            user_data["last_name"],
            user_data["email"],
            user_data["password"],
            user_data.get("academy"),
            certificate_url=user_data.get("certificate_url"),
            student_id=user_data.get("student_id"),
        )
    finally:
        delete_otp_memory(email)

    return {"message": "Register success"}


@router.get("/me", response_model=MeResponse)
async def get_user_data(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
):
    user = get_user_data_service(db, current_user["id"])
    return map_user_to_me_response(user)

def map_user_to_me_response(user: User):
    return {
        "user": user,
                "roles": {
            "id": user.role.id,
            "name": user.role.name.value, 
        } if user.role else None,

    } 
    
@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(
        key="access_token",
        path="/",
        httponly=True,
        samesite="lax",  
        secure=False 
    )
    return {"message": "Logged out"}

