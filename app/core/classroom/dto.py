from pydantic import BaseModel
from typing import List, Optional


class LearningOutcomeDTO(BaseModel):
    id: int
    description: Optional[str]

    class Config:
        from_attributes = True


class SyllabusResponseDTO(BaseModel):
    classroom_name: str
    teacher_name: str
    classroom_description: Optional[str]
    learning_outcomes: List[LearningOutcomeDTO]

    class Config:
        from_attributes = True


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


class LearningOutcomeUpdateDTO(BaseModel):
    id: Optional[int]
    description: str


class ClassroomUpdateDTO(BaseModel):
    name: Optional[str]
    description: Optional[str]
    learning_outcomes: Optional[List[LearningOutcomeUpdateDTO]]