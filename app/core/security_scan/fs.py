import os
from pathlib import Path
import json
import logging

logger = logging.getLogger(__name__)

SUBMISSIONS_DIR = Path(os.environ["SUBMISSIONS_DIR"]).resolve()
RESULTS_DIR = Path(os.environ["RESULTS_DIR"]).resolve()

# ภาษาที่รองรับ
LANGUAGE_SIGNATURES = {
    "javascript": ["*.js", "*.ts", "*.jsx", "*.tsx", "package.json"],
    "python": ["*.py", "requirements.txt", "pyproject.toml"],
    "java": ["*.java", "pom.xml", "build.gradle"],
    "go": ["*.go", "go.mod"],
    "php": ["*.php", "composer.json"],
    "c": ["*.c", "*.h"],
    "cpp": ["*.cpp", "*.hpp", "*.cc", "*.cxx"],
    "csharp": ["*.cs", "*.csproj"],
    "ruby": ["*.rb", "Gemfile"],
    "kotlin": ["*.kt", "*.kts"],
    "swift": ["*.swift"]
}

def ensure_dirs():
    SUBMISSIONS_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"Directories ready: {SUBMISSIONS_DIR}, {RESULTS_DIR}")

def get_submission_path(submission_id: str) -> Path:
    return SUBMISSIONS_DIR / submission_id

def detect_languages(path: Path) -> list:
    """ตรวจสอบภาษาที่มีในโฟลเดอร์"""
    detected = []
    
    for lang, patterns in LANGUAGE_SIGNATURES.items():
        for pattern in patterns:
            if list(path.rglob(pattern)):
                detected.append(lang)
                break
    
    return detected

def validate_submission(path: Path) -> dict:
    """ตรวจสอบว่ามีไฟล์ source code หรือไม่"""
    languages = detect_languages(path)
    
    # นับไฟล์ทั้งหมด
    all_files = list(path.rglob("*"))
    code_files = [f for f in all_files if f.is_file() and not f.name.startswith('.')]
    
    logger.info(f"Found {len(code_files)} files in {path}")
    logger.info(f"Detected languages: {languages}")
    
    return {
        "has_files": len(code_files) > 0,
        "languages": languages,
        "file_count": len(code_files)
    }

def save_result(submission_id: str, result: dict):
    out = RESULTS_DIR / f"{submission_id}.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Result saved: {out}")

def get_project_info():
    """แสดงข้อมูล environment สำหรับ debug"""
    import os
    return {
        "submissions_dir": os.environ.get("SUBMISSIONS_DIR"),
        "results_dir": os.environ.get("RESULTS_DIR"),
        "snyk_image": os.environ.get("SNYK_IMAGE")
    }