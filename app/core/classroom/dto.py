from pydantic import BaseModel
from typing import List, Optional

class StudentDTO(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: str
    student_id: Optional[str]
    image_url: Optional[str]

    class Config:
        from_attributes = True


class ClassroomStudentsResponseDTO(BaseModel):
    total_students: int
    students: list[StudentDTO]
