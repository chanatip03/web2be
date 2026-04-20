import enum
from sqlalchemy import (
    Boolean,
    Table,
    Column,
    Integer,
    String,
    DateTime,
    Enum,
    ForeignKey,
    UniqueConstraint,
    JSON
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.database import Base

class RoleEnum(enum.Enum):
    student = "student"
    teacher = "teacher"


class SubmissionTypeEnum(enum.Enum):
    file = "file"
    github = "github"

class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(50), nullable=False)
    password = Column(String(), nullable=False)

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String(50), nullable=False)
    last_name = Column(String(50), nullable=False)
    email = Column(String(50), unique=True, nullable=False)
    password = Column(String(), nullable=False)
    academy = Column(String(), nullable=True)
    image_url = Column(String, nullable=True)

    created_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_date = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_date = Column(DateTime(timezone=True), nullable=True)

    role_id = Column(Integer, ForeignKey("roles.id"))
    role = relationship("Role")

    student = relationship("Student", back_populates="user", uselist=False, cascade="all, delete-orphan")
    teacher = relationship("Teacher", back_populates="user", uselist=False, cascade="all, delete-orphan")

class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(Enum(RoleEnum, name="role_enum"), nullable=False, unique=True)

    created_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_date = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_date = Column(DateTime(timezone=True), nullable=True)

class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)

    student_id = Column(String(50), nullable=True)
    discord_user_id = Column(String(100), unique=True, nullable=True)

    created_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_date = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_date = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="student")
    classrooms = relationship("ClassroomMember", back_populates="student")
    group_members = relationship("GroupMember", back_populates="student")
    projects = relationship("Project", back_populates="student")

class Teacher(Base):
    __tablename__ = "teachers"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)

    certificate_url = Column(String, nullable=True)
    is_approved = Column(Boolean, default=False)

    created_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_date = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_date = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="teacher")
    classrooms = relationship("Classroom", back_populates="teacher")

class Classroom(Base):
    __tablename__ = "classrooms"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100))
    description = Column(String, nullable=True)
    semester = Column(String(50))
    code = Column(String(50))

    teacher_id = Column(Integer, ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False)

    learningoutcomes = Column(String, nullable=True)

    created_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_date = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_date = Column(DateTime(timezone=True), nullable=True)

    teacher = relationship("Teacher", back_populates="classrooms")
    members = relationship("ClassroomMember", back_populates="classroom", cascade="all, delete-orphan")
    assignments = relationship("Assignment", back_populates="classroom", cascade="all, delete-orphan")

class ClassroomMember(Base):
    __tablename__ = "classroom_members"

    id = Column(Integer, primary_key=True, index=True)

    classroom_id = Column(Integer, ForeignKey("classrooms.id", ondelete="CASCADE"), nullable=False)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)

    created_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_date = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_date = Column(DateTime(timezone=True), nullable=True)

    classroom = relationship("Classroom", back_populates="members")
    student = relationship("Student", back_populates="classrooms")

    __table_args__ = (
        UniqueConstraint("classroom_id", "student_id", name="uq_classroom_student"),
    )

class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True, index=True)

    classroom_id = Column(Integer, ForeignKey("classrooms.id", ondelete="CASCADE"), nullable=False)

    title = Column(String(100), nullable=False)
    description = Column(String, nullable=True)

    start_date = Column(DateTime(timezone=True), nullable=False)
    due_date = Column(DateTime(timezone=True), nullable=False)

    is_group = Column(Boolean, default=False)
    is_public = Column(Boolean, default=False)

    testcase_url = Column(String, nullable=True)
    plagiarism_result = Column(JSON, nullable=True)

    project_type_id = Column(Integer, ForeignKey("project_types.id", ondelete="CASCADE"), nullable=False)
    language_id = Column(Integer, ForeignKey("languages.id", ondelete="CASCADE"), nullable=True)

    created_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_date = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_date = Column(DateTime(timezone=True), nullable=True)

    classroom = relationship("Classroom", back_populates="assignments")
    attachments = relationship("Attachment", back_populates="assignment", cascade="all, delete-orphan")
    project_type = relationship("ProjectType", back_populates="assignments")
    language = relationship("Language", back_populates="assignments")
    groups = relationship("Group", back_populates="assignment", cascade="all, delete-orphan")

class Attachment(Base):
    __tablename__ = "attachments"

    id = Column(Integer, primary_key=True, index=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False)

    file_url = Column(String, nullable=False)

    created_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_date = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_date = Column(DateTime(timezone=True), nullable=True)

    assignment = relationship("Assignment", back_populates="attachments")

class ProjectType(Base):
    __tablename__ = "project_types"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False, unique=True)

    assignments = relationship("Assignment", back_populates="project_type")

class Language(Base):
    __tablename__ = "languages"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False, unique=True)

    assignments = relationship("Assignment", back_populates="language")

class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)

    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=True)

    submission_type = Column(Enum(SubmissionTypeEnum, name="submission_type_enum"), nullable=False)
    project_source_url = Column(String, nullable=True)
    env = Column(String, nullable=False)
    container_id = Column(String, nullable=True)
    container_resource = Column(String, nullable=True)

    testcase_result = Column(String, nullable=True)
    cybersecurity_result = Column(String, nullable=True)
    score = Column(Integer, nullable=True)
    feedback = Column(String, nullable=True)
    is_late = Column(Boolean, default=False, nullable=False)

    created_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_date = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_date = Column(DateTime(timezone=True), nullable=True)
    
    group = relationship("Group", back_populates="projects")
    student = relationship("Student", back_populates="projects")

    @property
    def students(self):
        if self.group_id and self.group:
            return [member.student for member in self.group.members if member.student]
        return []

class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, index=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False)

    name = Column(String(50), nullable=False)

    created_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_date = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_date = Column(DateTime(timezone=True), nullable=True)

    assignment = relationship("Assignment", back_populates="groups")
    members = relationship("GroupMember", back_populates="group", cascade="all, delete-orphan")
    projects = relationship("Project", back_populates="group", cascade="all, delete-orphan")

class GroupMember(Base):
    __tablename__ = "group_members"

    id = Column(Integer, primary_key=True, index=True)

    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)

    created_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_date = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_date = Column(DateTime(timezone=True), nullable=True)

    group = relationship("Group", back_populates="members")
    student = relationship("Student", back_populates="group_members")

    __table_args__ = (
        UniqueConstraint("group_id", "student_id", name="uq_group_student"),
    )