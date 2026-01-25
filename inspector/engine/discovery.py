import os
import json
import re
import requests


def discover_openapi(project_path: str, base_url: str | None = None):
    """
    Discover OpenAPI specs from:
    1) Existing swagger/openapi files
    2) Runtime endpoints
    3) Static source code analysis
    """
    specs = []

    # --------------------------------
    # 1. Existing OpenAPI files
    # --------------------------------
    for root, _, files in os.walk(project_path):
        for f in files:
            if f.lower() in ("openapi.json", "swagger.json"):
                try:
                    with open(os.path.join(root, f), "r", encoding="utf-8") as fh:
                        specs.append(fh.read())
                except Exception as e:
                    print("[WARN] Cannot read", f, e)

    # --------------------------------
    # 2. Runtime discovery
    # --------------------------------
    if base_url:
        for path in ["/v3/api-docs", "/openapi.json", "/swagger/v1/swagger.json"]:
            try:
                r = requests.get(base_url + path, timeout=2)
                if r.status_code == 200:
                    specs.append(r.text)
            except requests.RequestException:
                pass

    # --------------------------------
    # 3. Static analysis (FastAPI)
    # --------------------------------
    paths = {}

    for root, _, files in os.walk(project_path):
        for f in files:
            if f.endswith(".py"):
                file_path = os.path.join(root, f)
                try:
                    with open(file_path, "r", encoding="utf-8") as fh:
                        code = fh.read()
                except Exception:
                    continue

                matches = re.findall(
                    r"@app\.(get|post|put|delete|patch)\(\"(.*?)\"",
                    code
                )

                for method, route in matches:
                    paths.setdefault(route, {})
                    paths[route][method] = {
                        "responses": {
                            "200": {"description": "Auto discovered"}
                        }
                    }

    if paths:
        specs.append(json.dumps({
            "openapi": "3.0.0",
            "info": {
                "title": "Auto Discovered API",
                "version": "1.0.0"
            },
            "paths": paths
        }))

    return specs