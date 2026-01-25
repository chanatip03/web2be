import os
import zipfile
import subprocess
import time
import requests
import ast
from typing import List


# -------------------------
# Prepare project
# -------------------------
def prepare_project(input_path: str) -> str:
    if not os.path.exists(input_path):
        raise ValueError(f"Path not found: {input_path}")

    if zipfile.is_zipfile(input_path):
        out_dir = input_path.replace(".zip", "")
        if not os.path.exists(out_dir):
            with zipfile.ZipFile(input_path, "r") as z:
                z.extractall(out_dir)
        input_path = out_dir

    if os.path.isdir(input_path):
        children = [
            d for d in os.listdir(input_path)
            if os.path.isdir(os.path.join(input_path, d))
        ]
        if len(children) == 1:
            return os.path.join(input_path, children[0])
        return input_path

    raise ValueError("Unsupported input")


# -------------------------
# Detect framework
# -------------------------
def detect_framework(project_path: str) -> str:
    files = os.listdir(project_path)

    if (
        "requirements.txt" in files
        or "pyproject.toml" in files
        or os.path.isdir(os.path.join(project_path, "app"))
    ):
        return "fastapi"

    if "package.json" in files:
        return "express"

    if "pom.xml" in files:
        return "spring"

    return "unknown"


# -------------------------
# Find FastAPI entrypoints
# -------------------------
def find_fastapi_entrypoints(project_path: str) -> List[str]:
    entrypoints = []

    for root, _, files in os.walk(project_path):
        for file in files:
            if not file.endswith(".py"):
                continue

            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, project_path)

            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read())
            except Exception:
                continue

            for node in ast.walk(tree):
                # จับทั้ง app = FastAPI() และ app: FastAPI = FastAPI()
                if isinstance(node, ast.Assign) or isinstance(node, ast.AnnAssign):
                    value = getattr(node, "value", None)
                    if isinstance(value, ast.Call):
                        func = value.func
                        if isinstance(func, ast.Name) and func.id == "FastAPI":
                            target = (
                                node.target if isinstance(node, ast.AnnAssign)
                                else node.targets[0]
                            )
                            if isinstance(target, ast.Name):
                                module = (
                                    rel_path
                                    .replace(os.sep, ".")
                                    .replace(".py", "")
                                )
                                entrypoints.append(f"{module}:{target.id}")

    return list(set(entrypoints))


# -------------------------
# Run backend
# -------------------------
def run_backend(project_path: str, framework: str):
    if framework == "fastapi":
        entrypoints = find_fastapi_entrypoints(project_path)

        if not entrypoints:
            print("[ERROR] No FastAPI() found in source")
            return None, None

        for ep in entrypoints:
            env = os.environ.copy()
            env["PYTHONPATH"] = project_path

            print(f"[INFO] Trying FastAPI entrypoint: {ep}")

            p = subprocess.Popen(
                [
                    "uvicorn",
                    ep,
                    "--host", "0.0.0.0",
                    "--port", "8000",
                ],
                cwd=project_path,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            return p, "http://localhost:8000"

        return None, None

    if framework == "express":
        p = subprocess.Popen(["node", "index.js"], cwd=project_path)
        return p, "http://localhost:3000"

    if framework == "spring":
        p = subprocess.Popen(["./mvnw", "spring-boot:run"], cwd=project_path)
        return p, "http://localhost:8080"

    return None, None


# -------------------------
# Wait for service
# -------------------------
def wait_for_service(base_url: str) -> bool:
    if not base_url:
        return False

    # ลองหลาย path เผื่อไม่มี /
    paths = ["/", "/docs", "/openapi.json"]

    for _ in range(30):
        for path in paths:
            try:
                r = requests.get(base_url + path, timeout=1)
                if r.status_code < 500:
                    print("[INFO] Backend is up")
                    return True
            except requests.RequestException:
                pass
        time.sleep(1)

    print("[WARN] Backend did not start")
    return False
