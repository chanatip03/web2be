import os
import shutil
import zipfile
from pathlib import Path
from typing import Tuple
from dotenv import load_dotenv

load_dotenv()

SUBMISSIONS_DIR = os.path.abspath(os.getenv("SUBMISSIONS_DIR"))


def ensure_submissions_dir():
    Path(SUBMISSIONS_DIR).mkdir(parents=True, exist_ok=True)


def zip_directory(directory_path: str) -> bytes:
    if not os.path.isdir(directory_path):
        raise ValueError(f"Directory not found: {directory_path}")

    import io
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(directory_path):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, os.path.dirname(directory_path))
                zf.write(file_path, arcname)

    return zip_buffer.getvalue()


def unzip_file(zip_bytes: bytes, extract_to: str | None = None) -> str:
    ensure_submissions_dir()

    if extract_to is None:
        import uuid
        extract_to = str(uuid.uuid4())

    extract_path = os.path.join(SUBMISSIONS_DIR, extract_to)
    os.makedirs(extract_path, exist_ok=True)

    import io
    zip_buffer = io.BytesIO(zip_bytes)

    try:
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            zf.extractall(extract_path)
    except Exception as e:
        raise RuntimeError(f"Failed to unzip: {e}")

    return extract_path


def unzip_file_from_path(zip_file_path: str, extract_to: str | None = None) -> str:
    if not os.path.isfile(zip_file_path):
        raise ValueError(f"Zip file not found: {zip_file_path}")

    with open(zip_file_path, "rb") as f:
        zip_bytes = f.read()

    return unzip_file(zip_bytes, extract_to=extract_to)


def delete_directory() -> bool:
    try:
        if os.path.isdir("app/data/"):
            shutil.rmtree("app/data/")
            return True
        return False
    except Exception as e:
        raise RuntimeError(f"Failed to delete directory app/data/: {e}")