import subprocess
import os
import json
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

CODE_SCAN_TIMEOUT = 600


def resolve_snyk_cli() -> str:
    configured = os.environ.get("SNYK_CLI_PATH")
    if configured:
        return configured

    for candidate in ("snyk.cmd", "snyk.exe", "snyk"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved

    raise RuntimeError("Snyk CLI not found in PATH")

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
    
    snyk_cli = resolve_snyk_cli()

    cmd = [
        snyk_cli,
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
            timeout=CODE_SCAN_TIMEOUT,
            env={**os.environ, "SNYK_TOKEN": token}
        )

        stdout = (result.stdout or b"").decode("utf-8", errors="replace")
        stderr = (result.stderr or b"").decode("utf-8", errors="replace")
        
        logger.info(f"Exit code: {result.returncode}")
        
        if result.returncode >= 2:
            raise RuntimeError(f"Snyk error: {stderr or stdout}")

        if not stdout.strip():
            raise RuntimeError(f"Snyk returned no JSON output. stderr: {stderr}")
        
        return json.loads(stdout)
        
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON: {e}")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Timeout after {CODE_SCAN_TIMEOUT}s")
    except Exception as e:
        raise RuntimeError(f"Scan failed: {e}")