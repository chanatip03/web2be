from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from app.db.database import get_db
from .dto import CreateTeacherRequest, CreateTeacherResponse
from .service import create_teacher
from app.models.schema import User
from app.utils.r2 import upload_file
import uuid

router = APIRouter(prefix="/teacher", tags=["Teacher"])


@router.post("/", response_model=CreateTeacherResponse)
async def register_teacher(
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    academy: str = Form(...),
    part: str = Form(...),
    certificate: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    if certificate:
        content = await certificate.read()
        key = f"certificates/{uuid.uuid4()}.{certificate.filename.split('.')[-1]}"
        _, url = upload_file(key, content, content_type=certificate.content_type)
        certificate_url = url

    try:
        user = create_teacher(db, first_name, last_name, email, password, academy, certificate_url)
        return CreateTeacherResponse(id=user.id, email=user.email)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
