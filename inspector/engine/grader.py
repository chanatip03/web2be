# grader.py
import json
import requests


def grade(base_url: str, openapi_json: str) -> str:
    """
    Simple grading by calling discovered endpoints
    """
    score = 0
    details = []

    try:
        spec = json.loads(openapi_json)
    except json.JSONDecodeError:
        return json.dumps({"score": 0, "error": "Invalid OpenAPI"})

    paths = spec.get("paths", {})

    for path, methods in paths.items():
        for method in methods.keys():
            try:
                resp = requests.request(
                    method.upper(),
                    base_url + path,
                    timeout=3
                )
                if resp.status_code < 500:
                    score += 5
                    details.append(f"{method.upper()} {path} OK")
            except requests.RequestException:
                details.append(f"{method.upper()} {path} FAILED")

    return json.dumps({
        "score": score,
        "checked": len(details),
        "details": details
    }, indent=2)
