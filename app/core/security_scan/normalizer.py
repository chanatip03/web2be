def normalize_code_result(raw: dict) -> dict:
    issues = []

    for run in raw.get("runs", []):
        for res in run.get("results", []):
            issues.append({
                "rule": res.get("ruleId"),
                "severity": res.get("level"),
                "message": res.get("message", {}).get("text"),
                "locations": [
                    {
                        "file": loc.get("physicalLocation", {})
                                   .get("artifactLocation", {})
                                   .get("uri"),
                        "startLine": loc.get("physicalLocation", {})
                                       .get("region", {})
                                       .get("startLine"),
                        "endLine": loc.get("physicalLocation", {})
                                     .get("region", {})
                                     .get("endLine"),
                    }
                    for loc in res.get("locations", [])
                ]
            })

    return {
        "type": "code",
        "languages": raw.get("_meta", {}).get("languages", []),
        "issues_found": len(issues),
        "issues": issues
    }
