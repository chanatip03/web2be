from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.models.schema import User
from typing import List
from .dto import (
    CreateClassroomRequest,
    CreateClassroomResponse,
    ClassroomResponse,
    ClassroomListResponse
)
from .service import (
    create_new_classroom,
    get_teacher_classrooms,
    get_classroom_details
)
# from app.auth.dependencies import get_current_user

router = APIRouter(prefix="/classroom", tags=["Classroom"])


@router.post("/", response_model=CreateClassroomResponse, status_code=status.HTTP_201_CREATED)
def create_classroom_endpoint(
    data: CreateClassroomRequest,
    db: Session = Depends(get_db),
    # current_user: User = Depends(get_current_user)  # TODO: เพิ่ม auth
):
    """
    สร้าง classroom ใหม่ (เฉพาะครูเท่านั้น)
    
    Args:
        - name: ชื่อ classroom
        - semester: ภาคเรียน (เช่น "1/2025", "2/2025")
        - description: คำอธิบาย (optional)
    
    Returns:
        - id: ID ของ classroom
        - name: ชื่อ classroom
        - code: รหัสสำหรับเข้าร่วม classroom (8 ตัวอักษร)
        - semester: ภาคเรียน
        - teacher_id: ID ของครู
    """
    # TODO: ใช้ current_user.id แทน user_id_mock
    user_id_mock = 1  # สมมติว่า user_id = 1 เป็นครู (ต้องเปลี่ยนเป็น current_user.id)
    
    try:
        classroom = create_new_classroom(
            db=db,
            user_id=user_id_mock,
            name=data.name,
            semester=data.semester,
            description=data.description
        )
        
        return CreateClassroomResponse(
            id=classroom.id,
            name=classroom.name,
            code=classroom.code,
            semester=classroom.semester,
            teacher_id=classroom.teacher_id
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create classroom: {str(e)}"
        )


@router.get("/", response_model=ClassroomListResponse)
def get_classrooms_endpoint(
    db: Session = Depends(get_db),
    # current_user: User = Depends(get_current_user)  # TODO: เพิ่ม auth
):
    """
    ดึง classroom ทั้งหมดของครู
    
    Returns:
        - classrooms: รายการ classroom ทั้งหมดที่ครูสอน
        - total: จำนวน classroom ทั้งหมด
    """
    # TODO: ใช้ current_user.id แทน user_id_mock
    user_id_mock = 1  # สมมติ user_id (ต้องเปลี่ยนเป็น current_user.id)
    
    try:
        classrooms = get_teacher_classrooms(db, user_id_mock)
        
        classroom_responses = []
        for classroom in classrooms:
            details = get_classroom_details(db, classroom.id, user_id_mock)
            if details:
                classroom_responses.append(ClassroomResponse(**details))
        
        return ClassroomListResponse(
            classrooms=classroom_responses,
            total=len(classroom_responses)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch classrooms: {str(e)}"
        )


@router.get("/{classroom_id}", response_model=ClassroomResponse)
def get_classroom_endpoint(
    classroom_id: int,
    db: Session = Depends(get_db),
    # current_user: User = Depends(get_current_user)  # TODO: เพิ่ม auth
):
    """
    ดึงรายละเอียด classroom
    
    ต้องเป็นครูของ classroom นี้เท่านั้น
    """
    # TODO: ใช้ current_user.id แทน user_id_mock
    user_id_mock = 1  # สมมติ user_id (ต้องเปลี่ยนเป็น current_user.id)
    
    details = get_classroom_details(db, classroom_id, user_id_mock)
    
    if not details:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Classroom not found or access denied"
        )
    
    return ClassroomResponse(**details)