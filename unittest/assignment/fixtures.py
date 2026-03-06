from datetime import datetime, timezone, timedelta
from app.models.schema import Assignment, Attachment, ProjectType, Language


def seed_project_type(db, name="Web"):
    pt = ProjectType(name=name)
    db.add(pt)
    db.commit()
    db.refresh(pt)
    return pt


def seed_language(db, name="Python"):
    lang = Language(name=name)
    db.add(lang)
    db.commit()
    db.refresh(lang)
    return lang


def seed_assignment(db, classroom_id, project_type_id,
                    language_id=None, title="Lab 1", deleted=False):
    now = datetime.now(timezone.utc)
    a = Assignment(
        title=title,
        description="Test description",
        start_date=now,
        due_date=now + timedelta(days=7),
        is_group=False,
        is_public=False,
        project_type_id=project_type_id,
        language_id=language_id,
        classroom_id=classroom_id,
        testcase_url=None,
        deleted_date=datetime.now(timezone.utc) if deleted else None,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def seed_attachment(db, assignment_id,
                    file_url="https://example.com/file.pdf", deleted=False):
    att = Attachment(
        file_url=file_url,
        assignment_id=assignment_id,
        deleted_date=datetime.now(timezone.utc) if deleted else None,
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return att