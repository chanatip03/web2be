from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.db.database import get_db
from typing import List
import csv
import io
from .dto import (
    CreateClassroomRequest,
    CreateClassroomResponse,
    ClassroomResponse,
    ClassroomListResponse,
    JoinClassroomRequest,
    JoinClassroomResponse
)
from .service import (
    create_new_classroom,
    get_teacher_classrooms,
    get_classroom_details,
    get_classroom_students_for_export,
    join_classroom_by_code
)

router = APIRouter(prefix="/classroom", tags=["Classroom"])


@router.post("/", response_model=CreateClassroomResponse, status_code=status.HTTP_201_CREATED)
def create_classroom_endpoint(
    data: CreateClassroomRequest,
    db: Session = Depends(get_db),
):
    """สร้าง classroom ใหม่ (เฉพาะครู)"""
    # TODO: ใช้ current_user.id แทน user_id_mock
    user_id_mock = 1
    
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


@router.post("/join", response_model=JoinClassroomResponse)
def join_classroom_endpoint(
    data: JoinClassroomRequest,
    db: Session = Depends(get_db),
):
    """นักเรียนเข้าร่วม classroom ด้วย code 6 ตัวอักษร"""
    # TODO: ใช้ current_user.id แทน user_id_mock
    user_id_mock = 2  # สมมติ user_id = 2 เป็นนักเรียน
    
    try:
        result = join_classroom_by_code(
            db=db,
            user_id=user_id_mock,
            code=data.code.upper()
        )
        
        return JoinClassroomResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to join classroom: {str(e)}"
        )


@router.get("/", response_model=ClassroomListResponse)
def get_classrooms_endpoint(
    db: Session = Depends(get_db),
):
    """ดึง classroom ทั้งหมดของครู"""
    # TODO: ใช้ current_user.id แทน user_id_mock
    user_id_mock = 1
    
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
):
    """ดึงรายละเอียด classroom"""
    # TODO: ใช้ current_user.id แทน user_id_mock
    user_id_mock = 1
    
    details = get_classroom_details(db, classroom_id, user_id_mock)
    
    if not details:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Classroom not found or access denied"
        )
    
    return ClassroomResponse(**details)


@router.get("/{classroom_id}/students/export")
def export_classroom_students(
    classroom_id: int,
    db: Session = Depends(get_db),
):
    """ดาวน์โหลดรายชื่อนักเรียนใน classroom เป็น CSV"""
    # TODO: ใช้ current_user.id แทน user_id_mock
    user_id_mock = 1
    
    students = get_classroom_students_for_export(db, classroom_id, user_id_mock)
    
    if students is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Classroom not found or access denied"
        )
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow(["Student ID", "First Name", "Last Name", "Email", "Academy", "Joined Date"])
    
    for student in students:
        writer.writerow([
            student["student_id"] or "",
            student["first_name"],
            student["last_name"],
            student["email"],
            student["academy"] or "",
            student["joined_date"].strftime("%Y-%m-%d %H:%M:%S") if student["joined_date"] else ""
        ])
    
    output.seek(0)
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=classroom_{classroom_id}_students.csv"
        }
    )