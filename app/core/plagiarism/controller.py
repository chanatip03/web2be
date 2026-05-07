from fastapi import APIRouter, HTTPException
from .repository import extract_avg_comparisons, run_jplag_service

router = APIRouter(prefix="/plagiarism", tags=["Plagiarism"])

@router.post("/check")
def check_plagiarism():
    try:
        jplag_file = run_jplag_service()
        result = extract_avg_comparisons(jplag_file)

        return {
            "status": "success",
            "total_comparisons": len(result),
            "data": result
        }

    except Exception as e:
        import traceback

        raise HTTPException(
            status_code=500,
            detail={
                "error": str(e),
                "traceback": traceback.format_exc()
            }
        )