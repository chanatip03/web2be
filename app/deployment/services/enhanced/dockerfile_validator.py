"""Dockerfile validator — security checks and best-practice scoring."""

from __future__ import annotations

import re
from typing import Any, Dict, List


class DockerfileValidator:
    """Validate a Dockerfile for security, best practices, and correctness."""

    def validate(self, content: str) -> Dict[str, Any]:
        errors: List[str] = []
        warnings: List[str] = []
        info: List[str] = []

        lines = content.split("\n")

        # FROM
        from_lines = [l for l in lines if l.strip().upper().startswith("FROM")]
        if not from_lines:
            errors.append("No FROM instruction found")
        else:
            for line in from_lines:
                if ":latest" in line or (":" not in line and "AS" not in line.upper()):
                    warnings.append(f"Using 'latest' tag is not recommended: {line.strip()}")

        # USER
        user_lines = [l for l in lines if l.strip().upper().startswith("USER")]
        if not user_lines:
            warnings.append("No USER instruction — container runs as root")
        elif any("root" in l.lower() or "USER 0" in l for l in user_lines):
            warnings.append("Container should not run as root")

        # EXPOSE
        expose_lines = [l for l in lines if l.strip().upper().startswith("EXPOSE")]
        if expose_lines:
            info.append(f"Exposed ports: {', '.join(l.strip() for l in expose_lines)}")

        # HEALTHCHECK
        if not any(l.strip().upper().startswith("HEALTHCHECK") for l in lines):
            warnings.append("No HEALTHCHECK — consider adding one")
        else:
            info.append("HEALTHCHECK defined")

        # Hardcoded secrets
        secret_patterns = [
            r'password\s*=\s*["\'][^"\']+["\']',
            r'api[_-]?key\s*=\s*["\'][^"\']+["\']',
            r'secret\s*=\s*["\'][^"\']+["\']',
            r'token\s*=\s*["\'][^"\']+["\']',
        ]
        for i, line in enumerate(lines, 1):
            for pattern in secret_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    errors.append(f"Line {i}: Possible hardcoded secret")

        # apt-get best practices
        for i, line in enumerate(lines):
            if "apt-get update" in line.lower():
                if i + 1 < len(lines) and "apt-get install" not in lines[i + 1].lower():
                    warnings.append(f"Line {i+1}: apt-get update should be combined with install")

        has_apt = any("apt-get" in l.lower() for l in lines)
        has_cleanup = any("rm -rf /var/lib/apt/lists" in l.lower() for l in lines)
        if has_apt and not has_cleanup:
            warnings.append("Consider cleaning apt cache to reduce image size")

        # COPY . .
        for i, line in enumerate(lines, 1):
            if re.match(r"^\s*COPY\s+\.\s+\.", line):
                warnings.append(f"Line {i}: COPY . . copies everything — use .dockerignore")

        # Score
        score = max(0, 100 - len(errors) * 20 - len(warnings) * 5)

        return {
            "valid": len(errors) == 0,
            "score": score,
            "errors": errors,
            "warnings": warnings,
            "info": info,
        }


dockerfile_validator = DockerfileValidator()
