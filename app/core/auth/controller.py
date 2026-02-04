from datetime import datetime, timezone
import uuid
from fastapi import File, Form, Request, Response, APIRouter, Depends, HTTPException, UploadFile
from pydantic import EmailStr
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.utils.r2 import upload_file
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
    )
from app.core.student.service import create_student
from app.core.teacher.service import create_teacher

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
async def request_otp(
    role: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: EmailStr = Form(...),
    password: str = Form(...),
    academy: str = Form(...),
    student_id: str | None = Form(None),
    certificate: UploadFile | None = File(None),
):
    otp = generate_otp()

    payload_data = {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "password": password,
        "academy": academy,
        "student_id": student_id,
    }

    if role == "teacher":
        if not certificate:
            raise HTTPException(400, "Certificate required")

        content = await certificate.read()
        key = f"certificates/{uuid.uuid4()}.{certificate.filename.split('.')[-1]}"
        _, url = upload_file(key, content, content_type=certificate.content_type)

        payload_data["certificate_url"] = url

    save_otp_memory(
    email=email,
    otp_hash=hash_otp(otp),
    payload={
        "role": role,
        "data": payload_data
    }
)
    print("SAVE OTP FOR:", email)

    send_otp_email(email, otp)
    return {"message": "OTP sent"}

@router.post("/verify-otp")
def verify_otp(email: str, otp: str, db: Session = Depends(get_db)):
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

    try:
        if role == "student":
            user = create_student(
                db,
                data["first_name"],
                data["last_name"],
                data["email"],
                data["password"],
                data.get("academy"),
                data.get("student_id"),
            )

        elif role == "teacher":
            user = create_teacher(
                db,
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
        "user_id": user.id,
        "role": role
    }


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


