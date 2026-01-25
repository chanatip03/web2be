from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Form
from fastapi.responses import JSONResponse
import shutil
import tempfile
import os
import zipfile
import subprocess
import time
import requests
import json
import re
import ast
from pathlib import Path
from typing import Optional, Dict, List

app = FastAPI(
    title="Auto Backend Inspector",
    description="Automated grading system for backend assignments",
    version="3.0.0"
)


# ====================================
# HELPER: Handle Multiple Files Upload
# ====================================
def create_project_from_files(files: List[UploadFile]) -> str:
    """สร้าง project directory จากหลายไฟล์ที่ upload มา"""
    temp_dir = tempfile.mkdtemp()
    
    for uploaded_file in files:
        # สร้าง path ตามโครงสร้างที่ส่งมา (รักษา directory structure)
        file_path = os.path.join(temp_dir, uploaded_file.filename)
        
        # สร้าง directory ถ้าจำเป็น
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        # บันทึกไฟล์
        with open(file_path, "wb") as f:
            shutil.copyfileobj(uploaded_file.file, f)
    
    return temp_dir


# ====================================
# HELPER: Extract Project
# ====================================
def extract_project(zip_file) -> str:
    """Extract ZIP to temp directory"""
    temp_dir = tempfile.mkdtemp()
    zip_path = os.path.join(temp_dir, "project.zip")
    
    with open(zip_path, "wb") as f:
        shutil.copyfileobj(zip_file, f)
    
    with zipfile.ZipFile(zip_path, 'r') as z:
        z.extractall(temp_dir)
    
    # ถ้ามี folder เดียว ให้เข้าไปใน folder นั้น
    items = [d for d in os.listdir(temp_dir) if d != "project.zip"]
    if len(items) == 1 and os.path.isdir(os.path.join(temp_dir, items[0])):
        return os.path.join(temp_dir, items[0])
    
    return temp_dir


# ====================================
# HELPER: Detect Framework
# ====================================
def detect_framework(project_path: str) -> Dict[str, any]:
    """Auto-detect framework and configuration"""
    files = os.listdir(project_path)
    
    framework_info = {
        "framework": "unknown",
        "entrypoint": None,
        "command": None,
        "port": 8000,
        "install_cmd": None
    }
    
    # FastAPI / Python
    if "requirements.txt" in files or "pyproject.toml" in files or any(f.endswith(".py") for f in files):
        framework_info["framework"] = "fastapi"
        framework_info["port"] = 8000
        
        # ค้นหา FastAPI instance
        entrypoints = find_fastapi_entrypoints(project_path)
        if entrypoints:
            framework_info["entrypoint"] = entrypoints[0]
            framework_info["command"] = ["uvicorn", entrypoints[0], "--host", "0.0.0.0", "--port", "8000"]
        
        if "requirements.txt" in files:
            framework_info["install_cmd"] = ["pip", "install", "-r", "requirements.txt"]
    
    # Express / Node.js
    elif "package.json" in files:
        framework_info["framework"] = "express"
        framework_info["port"] = 3000
        
        # อ่าน package.json เพื่อหา main file
        try:
            with open(os.path.join(project_path, "package.json")) as f:
                pkg = json.load(f)
                main_file = pkg.get("main", "index.js")
                framework_info["entrypoint"] = main_file
                framework_info["command"] = ["node", main_file]
                framework_info["install_cmd"] = ["npm", "install"]
        except:
            framework_info["command"] = ["node", "index.js"]
    
    # Spring Boot / Java
    elif "pom.xml" in files or "build.gradle" in files:
        framework_info["framework"] = "spring"
        framework_info["port"] = 8080
        
        if "mvnw" in files:
            framework_info["command"] = ["./mvnw", "spring-boot:run"]
        elif "gradlew" in files:
            framework_info["command"] = ["./gradlew", "bootRun"]
    
    # Django
    elif "manage.py" in files:
        framework_info["framework"] = "django"
        framework_info["port"] = 8000
        framework_info["command"] = ["python3", "manage.py", "runserver", "0.0.0.0:8000"]
        
        if "requirements.txt" in files:
            framework_info["install_cmd"] = ["pip", "install", "-r", "requirements.txt"]
    
    # Flask
    elif any("flask" in f.lower() or "app.py" in files for f in files):
        framework_info["framework"] = "flask"
        framework_info["port"] = 5000
        framework_info["entrypoint"] = "app:app"
        framework_info["command"] = ["flask", "run", "--host", "0.0.0.0", "--port", "5000"]
        
        if "requirements.txt" in files:
            framework_info["install_cmd"] = ["pip", "install", "-r", "requirements.txt"]
    
    return framework_info


def find_fastapi_entrypoints(project_path: str) -> List[str]:
    """Find all FastAPI app instances"""
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
                
                for node in ast.walk(tree):
                    if isinstance(node, (ast.Assign, ast.AnnAssign)):
                        value = getattr(node, "value", None)
                        if isinstance(value, ast.Call):
                            func = value.func
                            if isinstance(func, ast.Name) and func.id == "FastAPI":
                                target = (
                                    node.target if isinstance(node, ast.AnnAssign)
                                    else node.targets[0]
                                )
                                if isinstance(target, ast.Name):
                                    module = rel_path.replace(os.sep, ".").replace(".py", "")
                                    entrypoints.append(f"{module}:{target.id}")
            except:
                continue
    
    return entrypoints


# ====================================
# STEP 1: Static OpenAPI Discovery
# ====================================
def find_static_openapi(project_path: str) -> Optional[Dict]:
    """ค้นหาไฟล์ OpenAPI/Swagger ที่มีอยู่แล้ว"""
    openapi_files = ["openapi.json", "swagger.json", "openapi.yaml", "swagger.yaml"]
    
    for root, _, files in os.walk(project_path):
        for file in files:
            if file.lower() in openapi_files:
                try:
                    file_path = os.path.join(root, file)
                    with open(file_path, "r", encoding="utf-8") as f:
                        if file.endswith(".json"):
                            return json.load(f)
                except:
                    continue
    
    return None


# ====================================
# STEP 2: Static Code Analysis
# ====================================
def analyze_source_code(project_path: str, framework: str) -> Dict:
    """วิเคราะห์โค้ดเพื่อสร้าง OpenAPI spec"""
    paths = {}
    
    if framework == "fastapi":
        for root, _, files in os.walk(project_path):
            for file in files:
                if not file.endswith(".py"):
                    continue
                
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        code = f.read()
                    
                    pattern = r'@app\.(get|post|put|delete|patch)\(["\']([^"\']+)["\']\)'
                    matches = re.findall(pattern, code)
                    
                    for method, route in matches:
                        if route not in paths:
                            paths[route] = {}
                        paths[route][method] = {
                            "responses": {
                                "200": {"description": "Success"}
                            }
                        }
                except:
                    continue
    
    elif framework == "express":
        for root, _, files in os.walk(project_path):
            for file in files:
                if not file.endswith(".js"):
                    continue
                
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        code = f.read()
                    
                    pattern = r'(?:app|router)\.(get|post|put|delete|patch)\(["\']([^"\']+)["\']\)'
                    matches = re.findall(pattern, code)
                    
                    for method, route in matches:
                        if route not in paths:
                            paths[route] = {}
                        paths[route][method] = {
                            "responses": {
                                "200": {"description": "Success"}
                            }
                        }
                except:
                    continue
    
    if not paths:
        return None
    
    return {
        "openapi": "3.0.0",
        "info": {
            "title": "Auto-discovered API",
            "version": "1.0.0"
        },
        "paths": paths
    }


# ====================================
# STEP 3: Runtime Discovery
# ====================================
def discover_runtime_openapi(base_url: str) -> Optional[Dict]:
    """ลองเรียก endpoint ทั่วไปที่มักจะมี OpenAPI"""
    endpoints = [
        "/openapi.json",
        "/docs/openapi.json", 
        "/api/openapi.json",
        "/swagger.json",
        "/api-docs",
        "/v3/api-docs",
        "/swagger/v1/swagger.json"
    ]
    
    for endpoint in endpoints:
        try:
            response = requests.get(base_url + endpoint, timeout=2)
            if response.status_code == 200:
                return response.json()
        except:
            continue
    
    return None


# ====================================
# STEP 4: Run Backend & Discover
# ====================================
def run_and_discover(project_path: str, framework_info: Dict) -> tuple[Optional[subprocess.Popen], Optional[Dict]]:
    """รัน backend และค้นหา OpenAPI"""
    
    if framework_info["install_cmd"]:
        try:
            subprocess.run(
                framework_info["install_cmd"],
                cwd=project_path,
                timeout=120,
                capture_output=True
            )
        except:
            pass
    
    if not framework_info["command"]:
        return None, None
    
    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = project_path
        
        process = subprocess.Popen(
            framework_info["command"],
            cwd=project_path,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        base_url = f"http://localhost:{framework_info['port']}"
        for _ in range(30):
            try:
                response = requests.get(base_url, timeout=1)
                if response.status_code < 500:
                    openapi_spec = discover_runtime_openapi(base_url)
                    return process, openapi_spec
            except:
                pass
            time.sleep(1)
        
        return process, None
        
    except Exception as e:
        print(f"Failed to start backend: {e}")
        return None, None


# ====================================
# Generate Simple Rubric
# ====================================
def generate_simple_rubric(openapi_spec: Dict, total_points: int = 100) -> Dict:
    """สร้าง rubric แบบง่าย"""
    paths = openapi_spec.get("paths", {})
    
    if not paths:
        return {
            "assignment_name": "Simple Rubric",
            "total_points": total_points,
            "endpoints": [],
            "bonus_checks": []
        }
    
    endpoints = []
    
    for path, methods in paths.items():
        for method, details in methods.items():
            method_upper = method.upper()
            
            if method_upper == "POST":
                expected_status = 201
            elif method_upper == "DELETE":
                expected_status = [200, 204]
            else:
                expected_status = 200
            
            endpoint_rule = {
                "name": f"{method_upper} {path}",
                "path": path,
                "method": method_upper,
                "score": total_points,
                "expected_status": expected_status,
                "all_or_nothing": True
            }
            
            endpoints.append(endpoint_rule)
    
    return {
        "assignment_name": "Simple Rubric",
        "total_points": total_points,
        "endpoints": endpoints,
        "grading_mode": "simple",
        "bonus_checks": []
    }


# ====================================
# Grade Project
# ====================================
def grade_project(openapi_spec: Dict, base_url: Optional[str], rubric: Dict) -> Dict:
    """ตรวจคะแนนตาม rubric"""
    total_score = 0
    max_score = rubric.get("total_points", 100)
    details = []
    grading_mode = rubric.get("grading_mode", "proportional")
    
    all_passed = True
    
    for rule in rubric.get("endpoints", []):
        path = rule["path"]
        method = rule["method"].upper()
        score = rule["score"]
        
        result = {
            "name": rule.get("name", f"{method} {path}"),
            "path": path,
            "method": method,
            "max_score": score if grading_mode == "proportional" else max_score,
            "earned_score": 0,
            "status": "FAIL",
            "message": ""
        }
        
        if not openapi_spec or path not in openapi_spec.get("paths", {}):
            result["message"] = "Endpoint not found in API"
            details.append(result)
            all_passed = False
            continue
        
        if base_url:
            try:
                url = base_url + path
                kwargs = {"timeout": 5}
                
                if "request_body" in rule:
                    kwargs["json"] = rule["request_body"]
                
                response = requests.request(method, url, **kwargs)
                
                expected_status = rule.get("expected_status", 200)
                if isinstance(expected_status, list):
                    status_ok = response.status_code in expected_status
                else:
                    status_ok = response.status_code == expected_status
                
                if not status_ok:
                    result["message"] = f"Expected {expected_status}, got {response.status_code}"
                    if grading_mode == "proportional":
                        result["earned_score"] = score * 0.3
                        result["status"] = "PARTIAL"
                    all_passed = False
                else:
                    required_fields = rule.get("required_fields", [])
                    if required_fields:
                        try:
                            body = response.json()
                            if isinstance(body, list) and len(body) > 0:
                                body = body[0]
                            
                            missing = [f for f in required_fields if f not in body]
                            if missing:
                                result["message"] = f"Missing fields: {missing}"
                                if grading_mode == "proportional":
                                    result["earned_score"] = score * 0.7
                                    result["status"] = "PARTIAL"
                                all_passed = False
                            else:
                                result["message"] = "All checks passed"
                                result["earned_score"] = score if grading_mode == "proportional" else 0
                                result["status"] = "PASS"
                        except:
                            result["message"] = "Response validation failed"
                            if grading_mode == "proportional":
                                result["earned_score"] = score * 0.5
                                result["status"] = "PARTIAL"
                            all_passed = False
                    else:
                        result["message"] = "Request successful"
                        result["earned_score"] = score if grading_mode == "proportional" else 0
                        result["status"] = "PASS"
                
                if grading_mode == "proportional":
                    total_score += result["earned_score"]
                
            except Exception as e:
                result["message"] = f"Request failed: {str(e)}"
                all_passed = False
        else:
            result["message"] = "Found in spec (backend not tested)"
            if grading_mode == "proportional":
                result["earned_score"] = score * 0.4
                result["status"] = "PARTIAL"
                total_score += result["earned_score"]
            all_passed = False
        
        details.append(result)
    
    if grading_mode == "simple":
        total_score = max_score if all_passed else 0
    
    for bonus in rubric.get("bonus_checks", []):
        if bonus.get("check") == "openapi_exists" and openapi_spec:
            if grading_mode == "proportional":
                total_score += bonus["score"]
            details.append({
                "name": bonus["name"],
                "earned_score": bonus["score"] if grading_mode == "proportional" else 0,
                "status": "BONUS",
                "message": "OpenAPI documentation found"
            })
    
    return {
        "total": round(total_score, 2),
        "max_score": max_score,
        "percentage": round((total_score / max_score) * 100, 2) if max_score > 0 else 0,
        "grade": get_letter_grade(total_score, max_score),
        "grading_mode": grading_mode,
        "all_endpoints_passed": all_passed if grading_mode == "simple" else None,
        "details": details
    }


def get_letter_grade(score: float, max_score: float) -> str:
    """Convert score to letter grade"""
    percentage = (score / max_score) * 100
    if percentage >= 90: return "A"
    elif percentage >= 80: return "B"
    elif percentage >= 70: return "C"
    elif percentage >= 60: return "D"
    else: return "F"


# ====================================
# MAIN API ENDPOINT
# ====================================
@app.post("/inspect")
async def inspect_backend(
    file: UploadFile = File(None, description="ZIP file (single file)"),
    files: List[UploadFile] = File(None, description="Multiple files (folder structure)"),
    project_path: Optional[str] = Form(None, description="Local folder path (for same-server usage)"),
    rubric: Optional[str] = Query(None, description="Rubric file name"),
    grading_mode: str = Query("simple", description="Grading mode: 'simple' or 'proportional'")
):
    """
    Inspect Backend - 3 Ways to Submit
    
    **Option 1: Upload ZIP** (single file)
    - Use `file` parameter
    
    **Option 2: Upload Multiple Files** (แตก folder แล้ว) ⭐ แนะนำ!
    - Use `files` parameter
    - Upload ทุกไฟล์พร้อมกัน รักษา directory structure
    
    **Option 3: Local Path** (same server only)
    - Use `project_path` parameter
    - Works only if grader and project are on same machine
    """
    
    temp_project_path = None
    process = None
    
    try:
        # Validate input
        if not file and not files and not project_path:
            raise HTTPException(
                status_code=400,
                detail="Must provide one of: 'file' (ZIP), 'files' (multiple files), or 'project_path' (local folder)"
            )
        
        # Get project path based on input method
        if file:
            # Method 1: ZIP file
            temp_project_path = extract_project(file.file)
            actual_project_path = temp_project_path
            input_method = "zip"
        elif files:
            # Method 2: Multiple files
            temp_project_path = create_project_from_files(files)
            actual_project_path = temp_project_path
            input_method = "multiple_files"
        elif project_path:
            # Method 3: Local path
            if not os.path.exists(project_path):
                raise HTTPException(status_code=400, detail=f"Project path not found: {project_path}")
            actual_project_path = project_path
            input_method = "local_path"
        
        # Detect framework
        framework_info = detect_framework(actual_project_path)
        
        result = {
            "project_info": {
                "input_method": input_method,
                "filename": file.filename if file else None,
                "files_count": len(files) if files else None,
                "project_path": project_path if project_path else "temp",
                "framework": framework_info["framework"],
                "detected_entrypoint": framework_info.get("entrypoint")
            },
            "discovery_methods": [],
            "openapi_spec": None,
            "rubric_used": None,
            "grading_result": None
        }
        
        # STEP 1: Try static OpenAPI files
        openapi_spec = find_static_openapi(actual_project_path)
        if openapi_spec:
            result["discovery_methods"].append("static_file")
            result["openapi_spec"] = openapi_spec
        
        # STEP 2: Try source code analysis
        if not openapi_spec:
            openapi_spec = analyze_source_code(actual_project_path, framework_info["framework"])
            if openapi_spec:
                result["discovery_methods"].append("source_analysis")
                result["openapi_spec"] = openapi_spec
        
        # STEP 3: Try running backend
        base_url = None
        if framework_info["command"]:
            process, runtime_spec = run_and_discover(actual_project_path, framework_info)
            
            if runtime_spec:
                result["discovery_methods"].append("runtime")
                openapi_spec = runtime_spec
                result["openapi_spec"] = runtime_spec
                base_url = f"http://localhost:{framework_info['port']}"
            elif process:
                base_url = f"http://localhost:{framework_info['port']}"
        
        # STEP 4: Load or Generate Rubric
        rubric_data = None
        
        if rubric and os.path.exists(rubric):
            with open(rubric) as f:
                rubric_data = json.load(f)
            result["rubric_used"] = {
                "type": "provided",
                "file": rubric,
                "grading_mode": rubric_data.get("grading_mode", grading_mode)
            }
        elif openapi_spec:
            if grading_mode == "simple":
                rubric_data = generate_simple_rubric(openapi_spec)
            else:
                rubric_data = generate_simple_rubric(openapi_spec)
                rubric_data["grading_mode"] = "proportional"
                total_endpoints = len(rubric_data["endpoints"])
                score_per_endpoint = 100 // total_endpoints if total_endpoints > 0 else 0
                for endpoint in rubric_data["endpoints"]:
                    endpoint["score"] = score_per_endpoint
            
            result["rubric_used"] = {
                "type": "auto-generated",
                "endpoints_count": len(rubric_data["endpoints"]),
                "grading_mode": grading_mode
            }
        else:
            result["grading_result"] = {
                "total": 0,
                "max_score": 100,
                "percentage": 0,
                "grade": "F",
                "error": "Could not discover any API endpoints"
            }
            return result
        
        # STEP 5: Grade
        if rubric_data:
            grading_result = grade_project(openapi_spec, base_url, rubric_data)
            result["grading_result"] = grading_result
            result["generated_rubric"] = rubric_data if result["rubric_used"]["type"] == "auto-generated" else None
        
        return result
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "error": str(e),
                "type": type(e).__name__
            }
        )
    
    finally:
        if process:
            process.terminate()
            try:
                process.wait(timeout=5)
            except:
                process.kill()
        
        if temp_project_path and os.path.exists(temp_project_path):
            shutil.rmtree(temp_project_path, ignore_errors=True)


@app.get("/")
async def root():
    return {
        "name": "Auto Backend Inspector",
        "version": "3.0.0",
        "description": "Automated grading system for backend assignments",
        "features": [
            "✅ 3 input methods: ZIP, Multiple Files, or Local Path",
            "✅ Auto-detect framework",
            "✅ Multi-method API discovery",
            "✅ Two grading modes: simple or proportional",
            "✅ Dynamic rubric generation",
            "✅ Instant results"
        ],
        "usage": {
            "method_1": "Upload ZIP: POST /inspect with 'file' parameter",
            "method_2": "Upload Files: POST /inspect with 'files' parameter (multiple)",
            "method_3": "Local Path: POST /inspect with 'project_path' form data"
        }
    }


@app.get("/health")
async def health():
    return {"status": "healthy", "version": "3.0.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9000)