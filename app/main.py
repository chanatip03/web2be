from fastapi import FastAPI
from app.core import api_router
from fastapi import UploadFile, File, Form
from app.db.seed import run_seed
from app.utils.r2 import upload_file, get_file_bytes
from app.utils.archive import unzip_file, delete_directory
from fastapi.responses import JSONResponse
import os
from fastapi.middleware.cors import CORSMiddleware
from app.db.database import SessionLocal, engine, Base
import app.models
from app.deployment import router as deployment_router
import subprocess
import logging

import asyncio
from app.core.plagiarism.scheduler import start_plagiarism_scheduler

app = FastAPI(title="WEB2 API",redirect_slashes=False)
logger = logging.getLogger(__name__)

@app.on_event("startup")
def seed_data():
    try:
        subprocess.run(
            ["alembic", "upgrade", "head"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception as exc:
        logger.warning("Alembic upgrade failed; falling back to create_all: %s", exc)

    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        run_seed(db)
    finally:
        db.close()

@app.on_event("startup")
async def start_background_tasks():
    asyncio.create_task(start_plagiarism_scheduler())

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")
app.include_router(deployment_router)

@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/upload-test")
async def upload_test(path: str = Form(...), file: UploadFile = File(...)):
    """Test upload endpoint. Provide form fields: `path`, `filename`, and file upload.

    The file will be uploaded to R2 using the combined key `path/filename`.
    """
    content = await file.read()
    key = f"{path.rstrip('/')}/{file.filename}"
    try:
        _, url = upload_file(key, content, content_type=file.content_type)
        return JSONResponse({"key": key, "url": url})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/download-extract-test")
def download_extract_test(url: str):
    global student_counter
    try:
        base = f"{os.getenv('R2_URL').rstrip('/')}/{os.getenv('R2_BUCKET')}/"
        if not url.startswith(base):
            raise ValueError(f"Invalid R2 URL. Must start with {base}")
        key = url[len(base):]
        
        file_bytes = get_file_bytes(key)

        student_counter += 1
        extracted_path = unzip_file(file_bytes, extract_to="")
        
        return JSONResponse({
            "url": url,
            "key": key,
            "extracted_path": extracted_path,
        })
    except Exception as e:
        import traceback
        error_detail = f"{str(e)} | {traceback.format_exc()}"
        return JSONResponse({"error": error_detail}, status_code=500)


@app.delete("/delete-test")
def delete_test():
    """Test delete endpoint. Provide folder name within SUBMISSIONS_DIR.
    
    Deletes the folder and all its contents.
    """
    try:
        success = delete_directory()
        if success:
            return JSONResponse({"message": "Folder deleted successfully"})
        else:
            return JSONResponse({"error": "Folder not found"}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)