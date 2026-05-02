from typing import List, Optional
from fastapi import BackgroundTasks
from sqlalchemy.orm import Session
from .repository import get_project_by_id, get_projects_by_assignment_id, update_project_grading_repo
from .dto import ProjectResponse
from app.core.assignment.repository import get_assignment_by_id
from app.core.classroom.repository import is_classroom_of_teacher
from app.core.user.repository import get_teacher_by_user_id
from app.core.submission.fs import find_latest_manifest_for_project
from app.utils.otp import send_grading_discord, send_grading_email
from app.models.schema import Project, SubmissionTypeEnum
import io
import re
import zipfile
import os
import httpx
from concurrent.futures import ThreadPoolExecutor, as_completed

def build_file_node(path_parts: List[str], full_path: str, is_dir: bool) -> dict:
    return {
        "name": path_parts[-1],
        "type": "folder" if is_dir else "file",
        "path": full_path,
        "children": [] if is_dir else None
    }

def get_project_source_code_service(db: Session, current_user: dict, project_id: int) -> dict:
    project = get_project_by_id(db, project_id)
    if not project:
        raise ValueError("Project not found")

    if not project.project_source_url:
        raise ValueError("Project source code is not available")

    files_dict = {}
    
    root = {
        "name": "root",
        "type": "folder",
        "path": "",
        "children": []
    }

    folders = {"": root}

    def add_to_tree(path: str, is_dir: bool):
        parts = path.strip('/').split('/')
        if not parts or parts[0] == "":
            return
        
        current_path = ""
        parent = root
        for i, part in enumerate(parts):
            is_last = (i == len(parts) - 1)
            folder_path = f"{current_path}/{part}".strip('/')
            
            node_is_dir = not is_last or is_dir
            if folder_path not in folders:
                node = build_file_node(parts[:i+1], folder_path, node_is_dir)
                folders[folder_path] = node
                if parent["children"] is None:
                    parent["children"] = []
                parent["children"].append(node)
            parent = folders[folder_path]
            current_path = folder_path

    if project.submission_type == SubmissionTypeEnum.file or project.project_source_url.endswith('.zip'):
        try:
            from app.utils.r2 import R2_PUBLIC_URL, get_file_bytes
            key = project.project_source_url.replace(R2_PUBLIC_URL.rstrip('/') + "/", "")
            zip_bytes = get_file_bytes(key)
            
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
                for info in z.infolist():
                    if "__MACOSX" in info.filename or ".git/" in info.filename or info.filename.endswith("/"):
                        continue
                    
                    try:
                        content = z.read(info.filename).decode('utf-8')
                        files_dict[f"/{info.filename}"] = {"code": content}
                        add_to_tree(info.filename, is_dir=False)
                    except UnicodeDecodeError:
                        files_dict[f"/{info.filename}"] = {"code": "// Binary file"}
                        add_to_tree(info.filename, is_dir=False)
        except Exception as e:
            raise ValueError(f"Failed to read source code: {e}")
    else:
        # Parse GitHub URL to extract owner, repo, and optional branch
        match = re.match(
            r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/tree/([^/]+))?(?:/.*)?$",
            project.project_source_url.rstrip("/"),
        )
        if not match:
            raise ValueError(f"Unsupported repository URL: {project.project_source_url}")

        owner, repo, branch = match.group(1), match.group(2), match.group(3)
        gh_headers = {"Accept": "application/vnd.github.v3+json"}
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            gh_headers["Authorization"] = f"Bearer {token}"

        try:
            # Resolve default branch if not in URL
            if not branch:
                repo_resp = httpx.get(
                    f"https://api.github.com/repos/{owner}/{repo}",
                    headers=gh_headers,
                    timeout=15,
                )
                if not repo_resp.is_success:
                    raise ValueError(f"GitHub repo not found or rate-limited ({repo_resp.status_code})")
                branch = repo_resp.json().get("default_branch", "main")

            # Fetch recursive file tree
            tree_resp = httpx.get(
                f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1",
                headers=gh_headers,
                timeout=20,
            )
            if not tree_resp.is_success:
                raise ValueError(f"Failed to fetch file tree ({tree_resp.status_code})")

            SKIP_DIRS = {".git", "node_modules", "__pycache__", ".next", "dist", "build", ".venv", "venv"}
            blobs = [
                item["path"]
                for item in tree_resp.json().get("tree", [])
                if item["type"] == "blob"
                and not any(part in SKIP_DIRS for part in item["path"].split("/"))
            ][:300]  # hard cap to avoid giant repos

            # Concurrently fetch raw file content
            def fetch_raw(path: str):
                raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
                try:
                    resp = httpx.get(raw_url, headers=gh_headers, timeout=15)
                    if resp.is_success:
                        try:
                            return path, resp.content.decode("utf-8")
                        except UnicodeDecodeError:
                            return path, "// Binary file"
                    return path, f"// Failed to load ({resp.status_code})"
                except Exception as exc:
                    return path, f"// Error: {exc}"

            with ThreadPoolExecutor(max_workers=10) as pool:
                futures = {pool.submit(fetch_raw, p): p for p in blobs}
                for future in as_completed(futures):
                    rel_path, content = future.result()
                    files_dict[f"/{rel_path}"] = {"code": content}
                    add_to_tree(rel_path, is_dir=False)

        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Failed to fetch GitHub repository: {e}")
                
    return {
        "projectTree": root,
        "files": files_dict
    }


# def _to_project_response(project: Project) -> ProjectResponse:
#     manifest = find_latest_manifest_for_project(project.id)
#     return ProjectResponse.model_validate({
#         "id": project.id,
#         "assignment_id": project.assignment_id,
#         "student_id": project.student_id,
#         "group_id": project.group_id,
#         "submission_type": project.submission_type,
#         "submission_uuid": project.submission_uuid,
#         "project_source_url": project.project_source_url,
#         "env": project.env,
#         "testcase_result": project.testcase_result,
#         "cybersecurity_result": project.cybersecurity_result,
#         "score": project.score,
#         "feedback": project.feedback,
#         "is_late": project.is_late,
#         "created_date": project.created_date,
#         "submission_id": manifest.submission_id if manifest else None,
#         "students": list(project.students),
#     })


def get_project_service(db: Session, current_user: dict, project_id: int) -> ProjectResponse:
    project = get_project_by_id(db, project_id)
    return project

def get_projects_by_assignment_service(db: Session, current_user: dict, assignment_id: int) -> List[ProjectResponse]:
    assignment = get_assignment_by_id(db, assignment_id)
    if not assignment:
        raise ValueError("Assignment not found")
    projects = get_projects_by_assignment_id(db, assignment_id)

    return [p for p in projects]

def update_project_grading_service(db: Session, current_user: dict, project_id: int, background_tasks: BackgroundTasks, score: Optional[int] = None, feedback: Optional[str] = None) -> ProjectResponse:
    if current_user.get("role") not in ["teacher", "admin"]:
        raise ValueError("Only teachers and admins can grade projects")

    project = get_project_by_id(db, project_id)
    if not project:
        raise ValueError("Project not found")

    assignment_id = project.assignment_id
    if not assignment_id and project.group_id and project.group:
        assignment_id = project.group.assignment_id

    if current_user.get("role") == "teacher":
        teacher = get_teacher_by_user_id(db, current_user["id"])
        if not teacher:
            raise ValueError("Teacher profile not found")

        if not assignment_id:
            raise ValueError("Project is not linked to any assignment")

        assignment = get_assignment_by_id(db, assignment_id)
        if not assignment or not is_classroom_of_teacher(db, assignment.classroom_id, teacher.id):
            raise ValueError("Access denied to grade this project")

    project = update_project_grading_repo(db, project, score, feedback)

    if assignment_id:
        assignment = get_assignment_by_id(db, assignment_id)
        if assignment:
            assignment_name = assignment.title
            notification_targets = set()
            if project.group_id and project.group:
                for member in project.group.members:
                    if member.student and member.student.user:
                        notification_targets.add((member.student.user.email, member.student.discord_user_id))
            elif project.student and project.student.user:
                notification_targets.add((project.student.user.email, project.student.discord_user_id))

            for email, discord_user_id in notification_targets:
                if email:
                    background_tasks.add_task(
                        send_grading_email,
                        to_email=email,
                        assignment_name=assignment_name,
                        score=score,
                        feedback=feedback,
                    )
                if discord_user_id:
                    background_tasks.add_task(
                        send_grading_discord,
                        discord_user_id=discord_user_id,
                        assignment_name=assignment_name,
                        score=score,
                        feedback=feedback,
                    )

    return project
