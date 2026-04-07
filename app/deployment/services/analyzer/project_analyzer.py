"""Project analysis orchestrator — uses LLM + AST code parsing."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict

from app.deployment.core.exceptions import AnalysisError
from app.deployment.models.project import ProjectAnalysis
from app.deployment.services.analyzer.code_parser import parse_project_code
from app.deployment.services.analyzer.file_scanner import build_file_tree, sample_key_files
from app.deployment.services.llm.client import llm_client
from app.deployment.services.llm.parser import extract_json
from app.deployment.services.llm.prompts import ANALYSIS_SYSTEM, ANALYSIS_USER

logger = logging.getLogger(__name__)


async def analyze_project(project_path: str) -> ProjectAnalysis:
    """Analyse a project directory and return a structured analysis.

    Steps:
    1. Scan files and build context
    2. Run AST / regex code parser (endpoints, UI elements, components)
    3. Try LLM analysis
    4. Merge code-parser results into backend_info
    """
    root = Path(project_path)
    if not root.exists():
        raise AnalysisError(f"Project path does not exist: {project_path}")

    logger.info("Analysing project: %s", root.name)

    # 1. Scan
    file_tree = build_file_tree(root)
    file_samples = sample_key_files(root)

    tree_str = json.dumps(file_tree, indent=2, ensure_ascii=False)
    samples_str = "\n\n".join(
        f"### {path}\n```\n{content}\n```"
        for path, content in file_samples.items()
    )

    # 2. AST / regex code parsing (fast, no LLM)
    parsed_code: Dict[str, Any] = {}
    try:
        parsed_code = parse_project_code(root)
        ep_count = parsed_code["summary"]["total_api_endpoints"]
        ui_count = parsed_code["summary"]["total_ui_elements"]
        logger.info("Code parser: %d endpoints, %d UI elements", ep_count, ui_count)
    except Exception as exc:
        logger.warning("Code parser error (non-fatal): %s", exc)

    # 3. Try LLM
    analysis: ProjectAnalysis | None = None
    try:
        user_prompt = ANALYSIS_USER.format(
            file_tree=tree_str,
            file_samples=samples_str,
        )
        result = await llm_client.analyze_json(ANALYSIS_SYSTEM, user_prompt)
        if result:
            analysis = ProjectAnalysis.model_validate(result)
            logger.info(
                "LLM analysis complete: type=%s, stack=%s",
                analysis.project_type, analysis.tech_stack,
            )
    except Exception as exc:
        logger.warning("LLM analysis failed: %s", exc)

    # 4. No heuristic fallback — LLM-only mode
    if analysis is None:
        raise AnalysisError("LLM analysis failed and heuristic fallback is disabled. Check LLM connectivity.")

    # 4b. Post-process: fix common Node backend port mis-detections (e.g., default 3000).
    try:
        be = dict(analysis.backend_info or {})
        lang = str(be.get("language") or "").lower()

        # Some LLM analyses don't populate `detected`; treat presence of a backend_info as a signal.
        looks_like_node = lang in {"javascript", "typescript", "node"}
        if looks_like_node or be.get("framework") in {"express", "nestjs", "fastify", "koa", "hono"}:
            # Choose backend root by finding a package.json under common locations.
            candidates: list[tuple[Path, str]] = []
            rel_hint = str(be.get("path") or ".")
            if rel_hint and rel_hint != ".":
                candidates.append((root / rel_hint, rel_hint))
            candidates.extend([
                (root / "backend", "backend"),
                (root / "server", "server"),
                (root / "api", "api"),
                (root, "."),
            ])

            backend_root: Path | None = None
            backend_rel: str | None = None
            for p, rel in candidates:
                if (p / "package.json").exists():
                    backend_root = p
                    backend_rel = rel
                    break

            if backend_root:
                pkg_path = backend_root / "package.json"
                scripts: dict[str, str] = {}
                try:
                    pkg = json.loads(pkg_path.read_text(encoding="utf-8", errors="ignore"))
                    raw_scripts = pkg.get("scripts", {})
                    if isinstance(raw_scripts, dict):
                        scripts = {k: v for k, v in raw_scripts.items() if isinstance(v, str)}
                except Exception:
                    scripts = {}

                script_text = "\n".join(scripts.values())
                entry_candidates: list[str] = []
                entry_candidates.extend(re.findall(r"([\w./-]+\.(?:ts|js))", script_text))
                entry_candidates.extend([
                    "src/index.ts",
                    "src/server.ts",
                    "src/main.ts",
                    "src/index.js",
                    "index.ts",
                    "index.js",
                    "server.js",
                    "app.js",
                ])

                def _infer_port_from_text(text: str) -> int | None:
                    for pat in (
                        r"process\.env\.PORT\s*\|\|\s*(\d{2,5})",
                        r"\bport\s*[:=]\s*(\d{2,5})\b",
                        r"\.listen\(\s*(\d{2,5})\b",
                    ):
                        mm = re.search(pat, text)
                        if mm:
                            try:
                                return int(mm.group(1))
                            except Exception:
                                pass
                    return None

                inferred_port: int | None = None
                seen: set[str] = set()
                for rel_entry in entry_candidates:
                    if rel_entry in seen:
                        continue
                    seen.add(rel_entry)
                    p = backend_root / rel_entry
                    if not p.exists() or not p.is_file():
                        continue
                    try:
                        text = p.read_text(encoding="utf-8", errors="ignore")
                    except Exception:
                        continue
                    inferred_port = _infer_port_from_text(text)
                    if inferred_port:
                        break

                changed = False
                if backend_rel and backend_rel != be.get("path"):
                    be["path"] = backend_rel
                    changed = True

                if inferred_port and inferred_port != be.get("port"):
                    logger.info(
                        "Overriding Node backend port %s → %s based on source scan",
                        be.get("port"),
                        inferred_port,
                    )
                    be["port"] = inferred_port
                    changed = True

                if changed:
                    analysis.backend_info = be
    except Exception as exc:
        logger.warning("Node port override skipped: %s", exc)

    # 5. Merge code-parser results into backend_info
    if parsed_code:
        backend_info = dict(analysis.backend_info or {})
        # Prefer LLM-detected endpoints; fall back / augment with parsed ones
        if not backend_info.get("api_endpoints") and parsed_code.get("api_endpoints"):
            backend_info["api_endpoints"] = parsed_code["api_endpoints"]
        # Always store the full code scan so callers can query it
        backend_info["code_scan"] = {
            "api_endpoints": parsed_code.get("api_endpoints", []),
            "ui_elements": parsed_code.get("ui_elements", []),
            "components": parsed_code.get("components", []),
            "routes": parsed_code.get("routes", []),
            "summary": parsed_code.get("summary", {}),
        }
        analysis.backend_info = backend_info

    return analysis
