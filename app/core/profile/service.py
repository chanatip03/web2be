import uuid
from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.utils.r2 import upload_file
from . import repository
from .dto import ProfileResponse, UpdateProfileRequest, UpdateProfileResponse, UploadImageResponse


def get_profile_service(db: Session, user_id: int) -> ProfileResponse:
    user = repository.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="ไม่พบข้อมูล user")

    student = repository.get_student_by_user_id(db, user_id)
    teacher = repository.get_teacher_by_user_id(db, user_id)

    return ProfileResponse(
        id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        email=user.email,
        academy=user.academy,
        image_url=user.image_url,
        student_id=student.student_id if student else None,
        discord_user_id=student.discord_user_id if student else None,
        certificate_url=teacher.certificate_url if teacher else None,
    )


def update_profile_service(
    db: Session,
    user_id: int,
    request: UpdateProfileRequest,
) -> UpdateProfileResponse:
    user = repository.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="ไม่พบข้อมูล user")

    updated_user = repository.update_user(
        db=db,
        user=user,
        first_name=request.first_name,
        last_name=request.last_name,
        academy=request.academy,
    )

    if request.student_id is not None:
        student = repository.get_student_by_user_id(db, user_id)
        if student:
            repository.update_student(db=db, student=student, student_id=request.student_id)

    return UpdateProfileResponse(
        message="แก้ไขข้อมูลสำเร็จ",
        first_name=updated_user.first_name,
        last_name=updated_user.last_name,
        email=updated_user.email,
        academy=updated_user.academy,
        image_url=updated_user.image_url,
        student_id=request.student_id,
    )


def upload_profile_image_service(
    db: Session,
    user_id: int,
    file: UploadFile,
) -> UploadImageResponse:
    user = repository.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="ไม่พบข้อมูล user")

    allowed_types = {"image/jpeg", "image/png", "image/webp"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="รองรับเฉพาะไฟล์ jpg, png, webp")

    ext = file.filename.rsplit(".", 1)[-1]
    object_key = f"profile/{user_id}/{uuid.uuid4()}.{ext}"

    content = file.file.read()
    _, image_url = upload_file(object_key, content, content_type=file.content_type)

    repository.update_user(db=db, user=user, image_url=image_url)

    return UploadImageResponse(
        message="อัปโหลดรูปโปรไฟล์สำเร็จ",
        image_url=image_url,
    )