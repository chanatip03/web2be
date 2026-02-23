import subprocess
import os
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CODE_SCAN_TIMEOUT = 600

def scan_source_code(source_path: Path) -> dict:

    token = os.environ.get("SNYK_TOKEN")
    if not token:
        raise RuntimeError("SNYK_TOKEN is not set")
    
    if not source_path.exists():
        raise RuntimeError(f"Path not found: {source_path}")
    
    # ตรวจสอบไฟล์
    files = list(source_path.rglob("*"))
    code_files = [f for f in files if f.is_file() and not f.name.startswith('.')]
    
    logger.info(f"Found {len(code_files)} files")
    if len(code_files) == 0:
        raise RuntimeError(f"No files in {source_path}")
    
    cmd = [
        "snyk",
        "code",
        "test",
        "--json",
        str(source_path)
    ]
    
    logger.info(f"Running Snyk: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=CODE_SCAN_TIMEOUT,
            env={**os.environ, "SNYK_TOKEN": token}
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