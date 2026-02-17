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
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func

Base = declarative_base()

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

role_users = Table(
    "role_users",
    Base.metadata,
    Column(
        "user_id",
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "role_id",
        Integer,
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "created_date",
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    ),
)

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

    roles = relationship("Role", secondary=role_users, back_populates="users")

    student = relationship("Student", back_populates="user", uselist=False, cascade="all, delete-orphan")
    teacher = relationship("Teacher", back_populates="user", uselist=False, cascade="all, delete-orphan")

class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(Enum(RoleEnum, name="role_enum"), nullable=False, unique=True)

    created_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_date = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_date = Column(DateTime(timezone=True), nullable=True)

    users = relationship("User", secondary=role_users, back_populates="roles")

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
    submission_of = relationship(
    "SubmissionOf",
    back_populates="student",
    cascade="all, delete-orphan"
)

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

    start_date = Column(DateTime, nullable=False, server_default=func.now())
    due_date = Column(DateTime, nullable=False)

    is_group = Column(Boolean, default=False)
    is_public = Column(Boolean, default=False)

    testcase_url = Column(String, nullable=True)
    plagiarism_result = Column(JSON, nullable=True)

    project_type_id = Column(Integer, ForeignKey("project_types.id", ondelete="CASCADE"), nullable=False)
    language_id = Column(Integer, ForeignKey("languages.id", ondelete="CASCADE"), nullable=False)

    created_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_date = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_date = Column(DateTime(timezone=True), nullable=True)

    classroom = relationship("Classroom", back_populates="assignments")
    attachments = relationship("Attachment", back_populates="assignment", cascade="all, delete-orphan")
    projects = relationship("Project", back_populates="assignment", cascade="all, delete-orphan")

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

class Language(Base):
    __tablename__ = "languages"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False, unique=True)

class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)

    assignment_id = Column(Integer, ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False)

    submission_type = Column(Enum(SubmissionTypeEnum, name="submission_type_enum"), nullable=False)
    env = Column(String, nullable=False)

    testcase_result = Column(String, nullable=True)
    cybersecurity_result = Column(String, nullable=True)
    score = Column(Integer, nullable=True)
    feedback = Column(String, nullable=True)

    created_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_date = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_date = Column(DateTime(timezone=True), nullable=True)

    assignment = relationship("Assignment", back_populates="projects")
    project_files = relationship("ProjectFile", back_populates="project", cascade="all, delete-orphan")
    project_git = relationship("ProjectGit", back_populates="project", uselist=False, cascade="all, delete-orphan")
    groups = relationship("Group", back_populates="project", cascade="all, delete-orphan")
    submission_of = relationship("SubmissionOf",back_populates="project",cascade="all, delete-orphan")

class ProjectFile(Base):
    __tablename__ = "project_files"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)

    file_url = Column(String, nullable=False)

    created_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_date = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_date = Column(DateTime(timezone=True), nullable=True)

    project = relationship("Project", back_populates="project_files")

class ProjectGit(Base):
    __tablename__ = "project_git"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)

    repo_url = Column(String, nullable=False)
    branch = Column(String, nullable=False)
    commit_hash = Column(String, nullable=False)

    created_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_date = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_date = Column(DateTime(timezone=True), nullable=True)

    project = relationship("Project", back_populates="project_git")

class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)

    name = Column(String(50), nullable=False)

    created_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_date = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_date = Column(DateTime(timezone=True), nullable=True)

    project = relationship("Project", back_populates="groups")
    members = relationship("GroupMember", back_populates="group", cascade="all, delete-orphan")

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
    
class SubmissionOf(Base):
    __tablename__ = "submission_of"

    id = Column(Integer, primary_key=True, index=True)

    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)

    created_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "student_id", name="uq_project_student"),
    )
    
    project = relationship("Project", back_populates="submission_of")
    student = relationship("Student", back_populates="submission_of")