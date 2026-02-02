from fastapi import FastAPI
from app.core import api_router
from fastapi import UploadFile, File, Form
from app.utils.r2 import upload_file, get_file_bytes
from app.utils.archive import unzip_file, delete_directory
from fastapi.responses import JSONResponse
import uuid
import os

app = FastAPI(title="WEB2 API")

app.include_router(api_router, prefix="/api")
# app.include_router(security_router, prefix="/security")

student_counter = 1

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
            return JSONResponse({"message": f"Folder deleted successfully"})
        else:
            return JSONResponse({"error": f"Folder not found"}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
