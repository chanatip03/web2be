import subprocess
import os
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CODE_SCAN_TIMEOUT = 600


def resolve_shared_path(container_path: Path) -> Path:
    """
    แปลง container path -> shared mount path
    
    ไม่ต้องจัดการกับ host path เลย ใช้ shared volume แทน
    
    Example:
    /app/data/submissions/student-node 
    -> /host/data/submissions/student-node
    """
    host_base = Path(os.environ.get("HOST_SUBMISSIONS_BASE", "/host/data/submissions"))
    submissions_dir = Path(os.environ.get("SUBMISSIONS_DIR", "/app/data/submissions"))
    
    # หา relative path
    try:
        relative_path = container_path.relative_to(submissions_dir)
    except ValueError:
        relative_path = Path(container_path.name)
    
    # สร้าง shared path
    shared_path = host_base / relative_path
    
    logger.info(f"Path resolution:")
    logger.info(f"  Container: {container_path}")
    logger.info(f"  Shared: {shared_path}")
    logger.info(f"  Exists: {shared_path.exists()}")
    
    return shared_path


def scan_source_code(source_path: Path) -> dict:
    """
    Scan source code ด้วย Snyk container
    ใช้ shared volume ผ่าน --volumes-from
    """
    token = os.environ.get("SNYK_TOKEN")
    image = os.environ.get("SNYK_IMAGE", "student-snyk-code:1.0")
    
    if not token:
        raise RuntimeError("SNYK_TOKEN is not set")
    
    # แปลงเป็น shared path
    shared_path = resolve_shared_path(source_path)
    
    # ตรวจสอบว่า path มีอยู่จริงใน shared volume
    if not shared_path.exists():
        logger.error(f"Shared path not found: {shared_path}")
        logger.error(f"Available paths in /host/data/submissions:")
        base = Path("/host/data/submissions")
        if base.exists():
            for item in base.iterdir():
                logger.error(f"  - {item.name}")
        raise RuntimeError(
            f"Path not found in shared volume: {shared_path}\n"
            f"Check docker-compose.yml has: ./data/submissions:/host/data/submissions:ro"
        )
    
    # ตรวจสอบไฟล์
    files = list(shared_path.rglob("*"))
    code_files = [f for f in files if f.is_file() and not f.name.startswith('.')]
    
    logger.info(f"Found {len(code_files)} files")
    if len(code_files) == 0:
        raise RuntimeError(f"No files in {shared_path}")
    
    # Run Snyk with volumes-from
    cmd = [
        "docker", "run", "--rm",
        "-e", f"SNYK_TOKEN={token}",
        "--volumes-from", "student-scanner",
        "--workdir", str(shared_path),
        image,
        "code", "test",
        "--json"
    ]
    
    logger.info(f"Running Snyk: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=CODE_SCAN_TIMEOUT
        )
        
        logger.info(f"Exit code: {result.returncode}")
        
        if result.returncode >= 2:
            raise RuntimeError(f"Snyk error: {result.stderr or result.stdout}")
        
        return json.loads(result.stdout)
        
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON: {e}")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Timeout after {CODE_SCAN_TIMEOUT}s")
    except Exception as e:
        raise RuntimeError(f"Scan failed: {e}")