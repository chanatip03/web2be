import logging
from pathlib import Path
from fastapi import FastAPI, HTTPException, Response, APIRouter, Depends, status
from pydantic import BaseModel
from .fs import get_submission_path, save_result, validate_submission
from .snyk_code import scan_source_code
from .normalizer import normalize_code_result

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/security")

class ScanRequest(BaseModel):
    submission_id: str

@router.post("/scan")
def scan(req: ScanRequest):
    source_path = get_submission_path(req.submission_id)
    
    # ตรวจสอบว่า submission มีอยู่และมีไฟล์
    if not source_path.exists():
        raise HTTPException(
            status_code=404, 
            detail=f"Submission '{req.submission_id}' not found"
        )
    
    # ตรวจสอบว่ามีไฟล์ source code
    validation = validate_submission(source_path)
    if not validation["has_files"]:
        raise HTTPException(
            status_code=400,
            detail=f"No source code files found in submission. Detected languages: {validation['languages']}"
        )
    
    logger.info(f"Scanning {req.submission_id} - Languages: {validation['languages']}")
    
    try:
        raw = scan_source_code(source_path)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    normalized = normalize_code_result(raw)
    save_result(req.submission_id, normalized)

    return {
        "submission_id": req.submission_id,
        "scan": normalized
    }