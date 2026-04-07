from __future__ import annotations

import json
import mimetypes
import os
import shutil
import time
import uuid
import zipfile
from pathlib import Path
from typing import Optional

from .manifest import ArtifactRecord, SubmissionManifest, touch_manifest


_REPO_ROOT = Path(__file__).resolve().parents[3]


def get_submission_base_dir() -> Path:
    configured = os.getenv("SUBMISSIONS_DIR")
    if configured:
        base = Path(configured)
        if not base.is_absolute():
            base = (_REPO_ROOT / configured).resolve()
    else:
        base = (_REPO_ROOT / "data" / "submissions").resolve()
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_submission_root(submission_id: str) -> Path:
    return get_submission_base_dir() / submission_id


def create_submission_root(submission_id: str) -> Path:
    root = get_submission_root(submission_id)
    (root / "original").mkdir(parents=True, exist_ok=True)
    (root / "source").mkdir(parents=True, exist_ok=True)
    (root / "artifacts").mkdir(parents=True, exist_ok=True)
    return root


def get_source_dir(submission_id: str) -> Path:
    return get_submission_root(submission_id) / "source"


def get_original_dir(submission_id: str) -> Path:
    return get_submission_root(submission_id) / "original"


def get_artifacts_dir(submission_id: str) -> Path:
    return get_submission_root(submission_id) / "artifacts"


def get_manifest_path(submission_id: str) -> Path:
    return get_submission_root(submission_id) / "manifest.json"


def write_manifest(manifest: SubmissionManifest) -> Path:
    touch_manifest(manifest)
    path = get_manifest_path(manifest.submission_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(manifest.model_dump(mode="json"), indent=2, ensure_ascii=False)

    last_error: OSError | None = None
    for _ in range(10):
        temp_path = path.with_name(f"{path.stem}.{uuid.uuid4().hex}.tmp")
        try:
            temp_path.write_text(payload, encoding="utf-8")
            temp_path.replace(path)
            return path
        except PermissionError as exc:
            last_error = exc
            temp_path.unlink(missing_ok=True)
            time.sleep(0.05)

    if last_error is not None:
        raise last_error
    return path


def read_manifest(submission_id: str) -> SubmissionManifest:
    path = get_manifest_path(submission_id)
    if not path.exists():
        raise FileNotFoundError(f"Submission manifest not found: {submission_id}")
    return SubmissionManifest.model_validate_json(path.read_text(encoding="utf-8"))


def save_uploaded_archive(submission_id: str, filename: str, contents: bytes) -> Path:
    original_dir = get_original_dir(submission_id)
    original_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename or "submission.zip").name
    archive_path = original_dir / safe_name
    archive_path.write_bytes(contents)
    return archive_path


def _find_project_root(base: Path) -> Path:
    entries = [entry for entry in base.iterdir() if not entry.name.startswith(".")]
    if len(entries) == 1 and entries[0].is_dir():
        return _find_project_root(entries[0])
    return base


def normalize_source_root(source_dir: Path) -> None:
    entries = [entry for entry in source_dir.iterdir() if not entry.name.startswith(".")]
    if len(entries) != 1 or not entries[0].is_dir():
        return

    project_root = _find_project_root(source_dir)
    if project_root == source_dir:
        return

    temp_dir = source_dir.parent / f"{source_dir.name}-normalized-{uuid.uuid4().hex[:8]}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    for item in project_root.iterdir():
        shutil.move(str(item), str(temp_dir / item.name))
    shutil.rmtree(source_dir, ignore_errors=True)
    temp_dir.rename(source_dir)


def extract_archive_to_source(archive_path: Path, source_dir: Path) -> None:
    source_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive_path, "r") as zip_file:
            for member in zip_file.infolist():
                target_path = (source_dir / member.filename).resolve()
                if not str(target_path).startswith(str(source_dir.resolve())):
                    raise RuntimeError("Archive contains invalid file paths")
            zip_file.extractall(source_dir)
    except zipfile.BadZipFile as exc:
        raise RuntimeError("Invalid ZIP file") from exc
    normalize_source_root(source_dir)


def copy_artifact_into_submission(
    submission_id: str,
    source_path: Path,
    category: str,
    *,
    name: Optional[str] = None,
) -> Path:
    source_path = source_path.resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Artifact source not found: {source_path}")

    dest_dir = get_artifacts_dir(submission_id) / category
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_name = Path(name or source_path.name).name
    dest_path = dest_dir / dest_name

    if dest_path.exists():
        if source_path != dest_path.resolve():
            shutil.copy2(source_path, dest_path)
    else:
        shutil.copy2(source_path, dest_path)

    return dest_path


def write_json_artifact(submission_id: str, category: str, filename: str, payload: dict) -> Path:
    artifact_dir = get_artifacts_dir(submission_id) / category
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / Path(filename).name
    artifact_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return artifact_path


def register_artifact(
    manifest: SubmissionManifest,
    *,
    absolute_path: Path,
    category: str,
    name: Optional[str] = None,
    content_type: Optional[str] = None,
) -> ArtifactRecord:
    root = get_submission_root(manifest.submission_id).resolve()
    path = absolute_path.resolve()
    relative_path = path.relative_to(root)
    guessed = content_type or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    record = ArtifactRecord(
        artifact_id=uuid.uuid4().hex,
        name=name or path.name,
        category=category,
        relative_path=str(relative_path),
        content_type=guessed,
    )
    manifest.artifacts.append(record)
    touch_manifest(manifest)
    return record


def set_artifact_download_urls(manifest: SubmissionManifest) -> SubmissionManifest:
    for artifact in manifest.artifacts:
        artifact.download_url = f"/api/submission/{manifest.submission_id}/artifacts/{artifact.artifact_id}"
    touch_manifest(manifest)
    return manifest


def resolve_artifact_path(manifest: SubmissionManifest, artifact_id: str) -> tuple[ArtifactRecord, Path]:
    root = get_submission_root(manifest.submission_id).resolve()
    for artifact in manifest.artifacts:
        if artifact.artifact_id != artifact_id:
            continue
        artifact_path = (root / artifact.relative_path).resolve()
        if not str(artifact_path).startswith(str(root)):
            raise PermissionError("Artifact path escapes submission root")
        if not artifact_path.exists():
            raise FileNotFoundError(f"Artifact file not found: {artifact.relative_path}")
        return artifact, artifact_path
    raise FileNotFoundError(f"Artifact not found: {artifact_id}")