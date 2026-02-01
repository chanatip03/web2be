from fastapi import APIRouter
from .repository import extract_avg_comparisons, run_jplag_service

router = APIRouter(prefix="/plagiarism", tags=["Plagiarism"])

@router.post("/check")
def check_plagiarism():
    jplag_file = run_jplag_service()
    result = extract_avg_comparisons(jplag_file)

    return {
        "status": "success",
        "total_comparisons": len(result),
        "data": result
    }