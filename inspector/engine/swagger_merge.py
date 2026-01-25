# swagger_merge.py
import json


def merge_openapi(specs: list[str]) -> str:
    merged = {
        "openapi": "3.0.0",
        "info": {
            "title": "Unified Auto Generated API",
            "version": "1.0.0"
        },
        "paths": {}
    }

    for spec_text in specs:
        try:
            spec = json.loads(spec_text)
        except json.JSONDecodeError:
            continue

        for path, methods in spec.get("paths", {}).items():
            merged["paths"].setdefault(path, {})
            merged["paths"][path].update(methods)

    return json.dumps(merged, indent=2)
