import os
import sys
import json
import time
from pathlib import Path

from engine.universal_runner import (
    prepare_project,
    detect_framework,
    run_backend,
    wait_for_service
)
from engine.discovery import discover_openapi
from engine.swagger_merge import merge_openapi
from engine.grader import grade


def main(input_path: str, rubric_path: str = "rubric.json"):
    """
    Main grading pipeline:
    1. Prepare & detect project
    2. Run backend
    3. Discover OpenAPI specs
    4. Grade against rubric
    5. Cleanup
    """
    
    print("[STEP 1] Preparing project...")
    project_path = prepare_project(input_path)
    
    print("[STEP 2] Detecting framework...")
    framework = detect_framework(project_path)
    print(f"[INFO] Framework detected: {framework}")
    
    if framework == "unknown":
        print("[ERROR] Cannot detect framework")
        return create_error_report("Unknown framework")
    
    print("[STEP 3] Starting backend...")
    process, base_url = run_backend(project_path, framework)
    
    if not process:
        print("[ERROR] Failed to start backend")
        return create_error_report("Backend failed to start")
    
    try:
        print("[STEP 4] Waiting for service to be ready...")
        is_ready = wait_for_service(base_url)
        
        if not is_ready:
            print("[WARN] Service not ready, using static analysis only")
            base_url = None
        
        print("[STEP 5] Discovering OpenAPI specs...")
        specs = discover_openapi(project_path, base_url)
        
        if not specs:
            print("[WARN] No OpenAPI specs found")
            merged_spec = create_empty_spec()
        else:
            print(f"[INFO] Found {len(specs)} spec(s)")
            merged_spec = merge_openapi(specs)
        
        # Save merged OpenAPI spec
        os.makedirs("reports", exist_ok=True)
        with open("reports/openapi.json", "w") as f:
            f.write(merged_spec)
        
        print("[STEP 6] Grading against rubric...")
        
        # Load rubric
        if not os.path.exists(rubric_path):
            print(f"[ERROR] Rubric not found: {rubric_path}")
            return create_error_report("Rubric file not found")
        
        with open(rubric_path, "r") as f:
            rubric = json.load(f)
        
        # Grade the project
        if base_url and is_ready:
            score_result = grade_with_live_backend(base_url, merged_spec, rubric)
        else:
            score_result = grade_static_only(merged_spec, rubric)
        
        # Save score
        with open("reports/score.json", "w") as f:
            json.dump(score_result, f, indent=2)
        
        print(f"[DONE] Score: {score_result['total']}/{score_result['max_score']}")
        print(f"[DONE] Reports saved in reports/")
        
        return score_result
        
    finally:
        # Always cleanup
        print("[CLEANUP] Stopping backend...")
        if process:
            process.terminate()
            process.wait(timeout=5)


def grade_with_live_backend(base_url: str, openapi_json: str, rubric: dict) -> dict:
    """Grade by calling actual API endpoints"""
    import requests
    
    spec = json.loads(openapi_json)
    total_score = 0
    max_score = rubric.get("total_points", 100)
    details = []
    
    for rule in rubric.get("endpoints", []):
        path = rule["path"]
        method = rule["method"].upper()
        score = rule["score"]
        
        result = {
            "name": rule.get("name", f"{method} {path}"),
            "path": path,
            "method": method,
            "max_score": score,
            "earned_score": 0,
            "status": "FAIL",
            "message": ""
        }
        
        # Check if path exists in OpenAPI
        if path not in spec.get("paths", {}):
            result["message"] = "Path not found in OpenAPI spec"
            details.append(result)
            continue
        
        try:
            # Prepare request
            url = base_url + path
            kwargs = {
                "timeout": 5,
                "headers": {"Content-Type": "application/json"}
            }
            
            # Add body if needed
            if "request_body" in rule:
                kwargs["json"] = rule["request_body"]
            
            # Send request
            response = requests.request(method, url, **kwargs)
            
            # Check status code
            expected_status = rule.get("expected_status", 200)
            if isinstance(expected_status, list):
                status_ok = response.status_code in expected_status
            else:
                status_ok = response.status_code == expected_status
            
            if not status_ok:
                result["message"] = f"Expected status {expected_status}, got {response.status_code}"
                details.append(result)
                continue
            
            # Check required fields (if response is JSON)
            required_fields = rule.get("required_fields", [])
            if required_fields and response.headers.get("content-type", "").startswith("application/json"):
                try:
                    body = response.json()
                    
                    # Handle array response
                    if isinstance(body, list) and len(body) > 0:
                        body = body[0]
                    
                    missing_fields = [f for f in required_fields if f not in body]
                    
                    if missing_fields:
                        result["earned_score"] = score * 0.5
                        result["status"] = "PARTIAL"
                        result["message"] = f"Missing fields: {missing_fields}"
                    else:
                        result["earned_score"] = score
                        result["status"] = "PASS"
                        result["message"] = "All checks passed"
                    
                except json.JSONDecodeError:
                    result["message"] = "Response is not valid JSON"
            else:
                # No field validation needed
                result["earned_score"] = score
                result["status"] = "PASS"
                result["message"] = "Request successful"
            
            total_score += result["earned_score"]
            
        except requests.RequestException as e:
            result["message"] = f"Request failed: {str(e)}"
        
        details.append(result)
    
    # Bonus checks
    for bonus in rubric.get("bonus_checks", []):
        if bonus.get("check") == "openapi_exists":
            if spec.get("paths"):
                total_score += bonus["score"]
                details.append({
                    "name": bonus["name"],
                    "earned_score": bonus["score"],
                    "status": "BONUS",
                    "message": "OpenAPI documentation found"
                })
    
    return {
        "total": round(total_score, 2),
        "max_score": max_score,
        "percentage": round((total_score / max_score) * 100, 2) if max_score > 0 else 0,
        "details": details,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }


def grade_static_only(openapi_json: str, rubric: dict) -> dict:
    """Grade based on OpenAPI spec only (no live backend)"""
    spec = json.loads(openapi_json)
    total_score = 0
    max_score = rubric.get("total_points", 100)
    details = []
    
    for rule in rubric.get("endpoints", []):
        path = rule["path"]
        method = rule["method"].lower()
        score = rule["score"]
        
        result = {
            "name": rule.get("name", f"{method.upper()} {path}"),
            "path": path,
            "method": method.upper(),
            "max_score": score,
            "earned_score": 0,
            "status": "FAIL",
            "message": "Backend not running - static check only"
        }
        
        # Check if path and method exist in spec
        paths = spec.get("paths", {})
        if path in paths and method in paths[path]:
            # Give partial credit for having the endpoint defined
            result["earned_score"] = score * 0.3
            result["status"] = "PARTIAL"
            result["message"] = "Endpoint found in spec (partial credit)"
            total_score += result["earned_score"]
        
        details.append(result)
    
    return {
        "total": round(total_score, 2),
        "max_score": max_score,
        "percentage": round((total_score / max_score) * 100, 2) if max_score > 0 else 0,
        "details": details,
        "warning": "Backend was not accessible - scores are based on static analysis only",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }


def create_empty_spec() -> str:
    """Create empty OpenAPI spec"""
    return json.dumps({
        "openapi": "3.0.0",
        "info": {
            "title": "No API Found",
            "version": "0.0.0"
        },
        "paths": {}
    })


def create_error_report(error_message: str) -> dict:
    """Create error report"""
    result = {
        "total": 0,
        "max_score": 100,
        "percentage": 0,
        "error": error_message,
        "details": [],
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # Save error report
    os.makedirs("reports", exist_ok=True)
    with open("reports/score.json", "w") as f:
        json.dump(result, f, indent=2)
    
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python main.py <project_path> [rubric_path]")
        sys.exit(1)
    
    rubric_path = sys.argv[2] if len(sys.argv) > 2 else "rubric.json"
    main(sys.argv[1], rubric_path)