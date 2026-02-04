import enum
from sqlalchemy import (
    Table,
    Column,
    Integer,
    String,
    DateTime,
    Enum,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Admin(Base):
     __tablename__ = "admins"

     id = Column(Integer, primary_key=True, index=True)
     email = Column(String(50) , nullable=False)
     password = Column(String() , nullable=False)
    
class RoleEnum(enum.Enum):
    student = "student"
    teacher = "teacher"

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
    roles = relationship(
        "Role",
        secondary=role_users,
        back_populates="users",
    )
    student = relationship(
        "Student",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    teacher = relationship(
        "Teacher",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(Enum(RoleEnum, name="role_enum"), nullable=False, unique=True)
    created_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_date = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_date = Column(DateTime(timezone=True), nullable=True)
    users = relationship(
        "User",
        secondary=role_users,
        back_populates="roles",
    )

class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    student_id = Column(String(50), nullable=True)
    discord_user_id = Column(String(100), unique=True, nullable=True)
    created_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_date = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_date = Column(DateTime(timezone=True), nullable=True)
    user = relationship("User", back_populates="student")
    classrooms = relationship("ClassroomMember", back_populates="student")

class Teacher(Base):
    __tablename__ = "teachers"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    certificate_url = Column(String, nullable=True)
    created_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_date = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_date = Column(DateTime(timezone=True), nullable=True)
    user = relationship("User", back_populates="teacher")
    classrooms = relationship("Classroom", back_populates="teacher")


class Classroom(Base):
    __tablename__ = "classrooms"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(String, nullable=True)
    semester = Column(String(50), nullable=True)
    code = Column(String(50), nullable=True)
    excel_link = Column(String, nullable=True)

    teacher_id = Column(
        Integer,
        ForeignKey("teachers.id", ondelete="CASCADE"),
        nullable=False,
    )

    created_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_date = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_date = Column(DateTime(timezone=True), nullable=True)

    teacher = relationship("Teacher", back_populates="classrooms")
    members = relationship(
        "ClassroomMember",
        back_populates="classroom",
        cascade="all, delete-orphan",
    )
    learning_outcomes = relationship(
        "LearningOutcome",
        back_populates="classroom",
        cascade="all, delete-orphan",
    )

class ClassroomMember(Base):
    __tablename__ = "classroom_members"

    id = Column(Integer, primary_key=True, index=True)
    classroom_id = Column(
        Integer,
        ForeignKey("classrooms.id", ondelete="CASCADE"),
        nullable=False,
    )
    student_id = Column(
        Integer,
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
    )

    created_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_date = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_date = Column(DateTime(timezone=True), nullable=True)

    classroom = relationship("Classroom", back_populates="members")
    student = relationship("Student", back_populates="classrooms")

    __table_args__ = (
        UniqueConstraint("classroom_id", "student_id", name="uq_classroom_student"),
    )

class LearningOutcome(Base):
    __tablename__ = "learning_outcomes"

    id = Column(Integer, primary_key=True, index=True)
    classroom_id = Column(
        Integer,
        ForeignKey("classrooms.id", ondelete="CASCADE"),
        nullable=False,
    )
    description = Column(String, nullable=True)

    created_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_date = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_date = Column(DateTime(timezone=True), nullable=True)

    classroom = relationship("Classroom", back_populates="learning_outcomes")
