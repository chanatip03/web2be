from sqlalchemy.orm import Session
from app.models.schema import Role, RoleEnum, ProjectType, Language


def seed_roles(db: Session):
    roles = [
        RoleEnum.student,
        RoleEnum.teacher,
    ]

    for role in roles:
        exists = db.query(Role).filter(Role.name == role).first()
        if not exists:
            db.add(Role(name=role))

    db.commit()


def seed_project_types(db: Session):
    project_types = [
        {"id": 1, "name": "Frontend"},
        {"id": 2, "name": "Backend"},
        {"id": 3, "name": "Project"},
    ]

    for pt in project_types:
        exists = db.query(ProjectType).filter(ProjectType.id == pt["id"]).first()
        if not exists:
            db.add(ProjectType(id=pt["id"], name=pt["name"]))

    db.commit()


def seed_languages(db: Session):
    languages = [
        {"id": 1, "name": "Java"},
        {"id": 2, "name": "Python"},
        {"id": 3, "name": "C"},
        {"id": 4, "name": "C++"},
        {"id": 5, "name": "JavaScript"},
        {"id": 6, "name": "TypeScript"},
        {"id": 7, "name": "Go"},
        {"id": 8, "name": "Kotlin"},
        {"id": 9, "name": "Swift"},
        {"id": 10, "name": "Rust"},
    ]

    for lang in languages:
        exists = db.query(Language).filter(Language.id == lang["id"]).first()
        if not exists:
            db.add(Language(id=lang["id"], name=lang["name"]))

    db.commit()


def run_seed(db: Session):
    seed_roles(db)
    seed_project_types(db)
    seed_languages(db)


if __name__ == "__main__":
    from app.db.database import SessionLocal

    print("🌱 Running seed...")

    db = SessionLocal()
    try:
        run_seed(db)
        print("✅ Seed completed")
    finally:
        db.close()