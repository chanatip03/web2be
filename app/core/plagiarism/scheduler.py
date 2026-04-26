import asyncio
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.db.database import SessionLocal
from app.models.schema import Assignment, Project
from app.utils.r2 import get_file_bytes, R2_PUBLIC_URL
from app.utils.archive import unzip_file
from app.core.plagiarism.repository import run_jplag_service, extract_avg_comparisons, BASE_PATH

logger = logging.getLogger(__name__)

def _extract_r2_key(url: str) -> str:
    if not url:
        return ""
    if R2_PUBLIC_URL and url.startswith(R2_PUBLIC_URL.rstrip('/')):
        return url.replace(R2_PUBLIC_URL.rstrip('/') + "/", "")
    
    # Try generic extraction if R2_PUBLIC_URL format differs
    if "submissions/" in url:
        return url[url.find("submissions/"):]
    return url

def _flatten_directory(path: str):
    """
    If a directory contains only one subdirectory and no files,
    move everything from that subdirectory up to the parent.
    This helps JPlag find files when students zip their entire project folder.
    """
    try:
        items = os.listdir(path)
        if len(items) == 1:
            subpath = os.path.join(path, items[0])
            if os.path.isdir(subpath):
                # Move all contents of subpath up to path
                for sub_item in os.listdir(subpath):
                    shutil.move(os.path.join(subpath, sub_item), os.path.join(path, sub_item))
                # Remove the now empty subpath
                os.rmdir(subpath)
                # Recurse in case it's nested multiple levels
                _flatten_directory(path)
    except Exception:
        pass # Safety check to prevent crashing the whole job if flattening fails

async def check_assignment_plagiarism(db: Session, assignment: Assignment):
    logger.info(f"Starting plagiarism check for Assignment {assignment.id}")
    
    # 1. Determine language
    language_name = "javascript"
    if assignment.language and assignment.language.name:
        language_name = assignment.language.name.lower()
    
    # 2. Get all projects (submissions) for this assignment
    projects = db.query(Project).filter(Project.assignment_id == assignment.id).all()
    if not projects:
        logger.info(f"No submissions found for Assignment {assignment.id}. Skipping.")
        assignment.plagiarism_result = [] # Set to empty to mark as checked
        db.commit()
        return

    # Create mapping from folder_name to actual student/group name
    name_mapping = {}

    # 3. Setup dynamic directories
    assignment_work_dir = os.path.abspath(os.path.join(BASE_PATH, "app", "data", "plagiarism_temp", f"assignment_{assignment.id}"))
    assignment_result_dir = os.path.abspath(os.path.join(BASE_PATH, "app", "data", "plagiarism_results", f"assignment_{assignment.id}"))
    
    os.makedirs(assignment_work_dir, exist_ok=True)
    os.makedirs(assignment_result_dir, exist_ok=True)

    try:
        # 4. Download and extract each project
        valid_submissions = 0
        for project in projects:
            if not project.project_source_url:
                continue
                
            folder_name = f"student_{project.student_id}" if project.student_id else f"group_{project.group_id}"
            if not folder_name:
                folder_name = f"project_{project.id}"
                
            # Store the actual name for the result mapping
            if project.group_id and project.group:
                name_mapping[folder_name] = project.group.name
            elif project.student_id and project.student and project.student.user:
                name_mapping[folder_name] = f"{project.student.user.first_name} {project.student.user.last_name}"
            else:
                name_mapping[folder_name] = folder_name

            extract_path = os.path.join(assignment_work_dir, folder_name)
            
            try:
                r2_key = _extract_r2_key(project.project_source_url)
                if not r2_key:
                    continue
                
                zip_bytes = get_file_bytes(r2_key)
                
                # unzip_file takes bytes and an extract_to path
                unzip_file(zip_bytes, extract_to=extract_path)
                _flatten_directory(extract_path)
                valid_submissions += 1
            except Exception as e:
                logger.error(f"Failed to download/extract project {project.id} for plagiarism check: {e}")

        # 5. Run JPlag if we have enough submissions
        if valid_submissions >= 2:
            try:
                jplag_file = run_jplag_service(
                    assignment_id=assignment.id,
                    language=language_name,
                    work_dir=assignment_work_dir,
                    result_dir=assignment_result_dir
                )
                
                # 6. Parse and save results
                result_json = extract_avg_comparisons(jplag_file)
                
                # Replace folder names with actual student/group names
                for result in result_json:
                    result["student1"] = name_mapping.get(result.get("student1"), result.get("student1"))
                    result["student2"] = name_mapping.get(result.get("student2"), result.get("student2"))

                assignment.plagiarism_result = result_json
                db.commit()
                logger.info(f"Plagiarism check completed for Assignment {assignment.id}")
            except Exception as e:
                logger.error(f"JPlag failed for Assignment {assignment.id}: {e}")
                # Mark as empty array so we don't infinitely retry failing assignments
                assignment.plagiarism_result = [] 
                db.commit()
        else:
            logger.info(f"Not enough valid submissions to run JPlag for Assignment {assignment.id}")
            assignment.plagiarism_result = []
            db.commit()

    finally:
        # 7. Clean up downloaded source codes and result zips
        shutil.rmtree(assignment_work_dir, ignore_errors=True)
        shutil.rmtree(assignment_result_dir, ignore_errors=True)

async def plagiarism_job():
    try:
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            # Find assignments where due_date is set, and it hasn't been checked yet
            # Checking plagiarism_result is None.
            assignments = db.query(Assignment).filter(
                Assignment.due_date != None,
                Assignment.plagiarism_result == None
            ).all()

            for assignment in assignments:
                # Ensure due_date is UTC aware for comparison
                due_date = assignment.due_date
                if due_date.tzinfo is None:
                    due_date = due_date.replace(tzinfo=timezone.utc)
                else:
                    due_date = due_date.astimezone(timezone.utc)
                
                check_time = due_date + timedelta(hours=3)
                
                if now >= check_time:
                    await check_assignment_plagiarism(db, assignment)

        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error in plagiarism scheduler job: {e}")

async def start_plagiarism_scheduler():
    logger.info("Starting plagiarism scheduler background task")
    while True:
        await plagiarism_job()
        await asyncio.sleep(60) # Run every minute
