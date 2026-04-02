"""Robot Framework test runner — execute .robot suites and collect results."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.deployment.core.config import settings
from app.deployment.services.logger import LoggerManager

logger = logging.getLogger(__name__)


# ── Disk persistence helpers ─────────────────────────────────────

def _results_dir(project_id: str) -> Path:
    d = Path(settings.projects_dir) / project_id / "tests" / ".results"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_result_to_disk(result: "TestResult") -> None:
    """Persist a TestResult as JSON so it survives server restarts."""
    try:
        path = _results_dir(result.project_id) / f"{result.test_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2, ensure_ascii=False, default=str)
    except Exception as exc:
        logger.warning("Failed to persist test result %s: %s", result.test_id, exc)


def _load_result_from_disk(project_id: str, test_id: str) -> Optional["TestResult"]:
    """Load a TestResult from disk."""
    try:
        path = _results_dir(project_id) / f"{test_id}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        r = TestResult()
        r.test_id = data["test_id"]
        r.project_id = data["project_id"]
        r.status = data["status"]
        r.started_at = data.get("started_at")
        r.finished_at = data.get("finished_at")
        r.total = data.get("total", 0)
        r.passed = data.get("passed", 0)
        r.failed = data.get("failed", 0)
        r.output = data.get("output", "")
        r.report_path = data.get("report_path")
        r.case_results = data.get("case_results", [])
        r.definition_test_id = data.get("definition_test_id")
        r.suite_version = data.get("suite_version")
        return r
    except Exception:
        return None


class TestResult:
    """Structured test execution result."""

    def __init__(self):
        self.test_id: str = str(uuid.uuid4())
        self.project_id: str = ""
        self.status: str = "pending"  # pending | running | passed | failed | error
        self.started_at: Optional[str] = None
        self.finished_at: Optional[str] = None
        self.total: int = 0
        self.passed: int = 0
        self.failed: int = 0
        self.output: str = ""
        self.report_path: Optional[str] = None
        self.case_results: List[Dict[str, Any]] = []
        self.definition_test_id: Optional[str] = None
        self.suite_version: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_id": self.test_id,
            "project_id": self.project_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "output": self.output[-3000:],  # Limit output size
            "report_path": self.report_path,
            "case_results": self.case_results,
            "definition_test_id": self.definition_test_id,
            "suite_version": self.suite_version,
        }


# In-memory cache (also persisted to disk)
_test_results: Dict[str, TestResult] = {}


async def run_robot_tests(project_id: str) -> TestResult:
    """Execute Robot Framework tests for a project."""
    proj_logger = LoggerManager.get(project_id)
    result = TestResult()
    result.project_id = project_id
    result.started_at = datetime.now().isoformat()
    _test_results[result.test_id] = result

    suite_dir = Path(settings.projects_dir) / project_id / "tests"
    suite_file = suite_dir / "test_suite.robot"

    if not suite_file.exists():
        result.status = "error"
        result.output = "No test suite found. Generate tests first."
        result.finished_at = datetime.now().isoformat()
        return result

    # Output directory
    output_dir = suite_dir / "results" / result.test_id
    output_dir.mkdir(parents=True, exist_ok=True)

    result.status = "running"
    proj_logger.info(f"Running Robot tests: {result.test_id}")

    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "robot",
            "--outputdir", str(output_dir),
            "--loglevel", "INFO",
            str(suite_file),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(suite_dir),
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=120
        )

        result.output = stdout.decode("utf-8", errors="replace")
        if stderr:
            result.output += "\n--- STDERR ---\n" + stderr.decode("utf-8", errors="replace")

        # Parse output.xml for results
        output_xml = output_dir / "output.xml"
        if output_xml.exists():
            result.case_results = _parse_robot_output(output_xml)
            result.total = len(result.case_results)
            result.passed = sum(1 for c in result.case_results if c.get("status") == "PASS")
            result.failed = result.total - result.passed
            result.status = "passed" if result.failed == 0 else "failed"
        else:
            result.status = "error" if process.returncode != 0 else "passed"

        # Check for report
        report_path = output_dir / "report.html"
        if report_path.exists():
            result.report_path = str(report_path)

    except asyncio.TimeoutError:
        result.status = "error"
        result.output = "Test execution timed out (120s)"
    except FileNotFoundError:
        result.status = "error"
        result.output = "Robot Framework not installed. Install with: pip install robotframework"
    except Exception as exc:
        result.status = "error"
        result.output = f"Test execution error: {exc}"

    result.finished_at = datetime.now().isoformat()
    proj_logger.log_test_run(result.total, result.passed, result.failed)
    logger.info("Test run %s: %s (pass=%d, fail=%d)", result.test_id, result.status, result.passed, result.failed)

    # Persist to disk so results survive restarts
    _save_result_to_disk(result)

    return result


async def run_robot_tests_with_suite_content(
    project_id: str,
    suite_content: str,
    *,
    definition_test_id: str,
    suite_version: Optional[int] = None,
) -> TestResult:
    """Execute Robot Framework tests from provided suite content."""
    proj_logger = LoggerManager.get(project_id)
    result = TestResult()
    result.project_id = project_id
    result.definition_test_id = definition_test_id
    result.suite_version = suite_version
    result.started_at = datetime.now().isoformat()
    _test_results[result.test_id] = result

    suite_dir = Path(settings.projects_dir) / project_id / "tests"
    suite_dir.mkdir(parents=True, exist_ok=True)
    generated_dir = suite_dir / ".generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    suite_file = generated_dir / f"{definition_test_id}.robot"
    suite_file.write_text(suite_content, encoding="utf-8")

    output_dir = suite_dir / "results" / result.test_id
    output_dir.mkdir(parents=True, exist_ok=True)

    result.status = "running"
    proj_logger.info(f"Running Robot tests from definition {definition_test_id}: {result.test_id}")

    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "robot",
            "--outputdir", str(output_dir),
            "--loglevel", "INFO",
            str(suite_file),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(suite_dir),
        )

        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=180)

        result.output = stdout.decode("utf-8", errors="replace")
        if stderr:
            result.output += "\n--- STDERR ---\n" + stderr.decode("utf-8", errors="replace")

        output_xml = output_dir / "output.xml"
        if output_xml.exists():
            result.case_results = _parse_robot_output(output_xml)
            result.total = len(result.case_results)
            result.passed = sum(1 for c in result.case_results if c.get("status") == "PASS")
            result.failed = result.total - result.passed
            result.status = "passed" if result.failed == 0 else "failed"
        else:
            result.status = "error" if process.returncode != 0 else "passed"

        report_path = output_dir / "report.html"
        if report_path.exists():
            result.report_path = str(report_path)

    except asyncio.TimeoutError:
        result.status = "error"
        result.output = "Test execution timed out (180s)"
    except FileNotFoundError:
        result.status = "error"
        result.output = "Robot Framework not installed. Install with: pip install robotframework"
    except Exception as exc:
        result.status = "error"
        result.output = f"Test execution error: {exc}"

    result.finished_at = datetime.now().isoformat()
    proj_logger.log_test_run(result.total, result.passed, result.failed)
    _save_result_to_disk(result)
    return result


def get_test_result(test_id: str) -> Optional[TestResult]:
    # Check memory first, then disk
    if test_id in _test_results:
        return _test_results[test_id]
    # Search all projects on disk (test_id is globally unique)
    projects_base = Path(settings.projects_dir)
    for results_path in projects_base.rglob(f".results/{test_id}.json"):
        project_id = results_path.parents[2].name
        result = _load_result_from_disk(project_id, test_id)
        if result:
            _test_results[test_id] = result  # cache in memory
            return result
    return None


def list_test_results(project_id: str) -> List[Dict[str, Any]]:
    # Merge in-memory and on-disk results
    seen: Dict[str, TestResult] = {}

    # From memory
    for r in _test_results.values():
        if r.project_id == project_id:
            seen[r.test_id] = r

    # From disk
    results_dir = _results_dir(project_id)
    for path in sorted(results_dir.glob("*.json"), reverse=True):
        test_id = path.stem
        if test_id not in seen:
            r = _load_result_from_disk(project_id, test_id)
            if r:
                seen[test_id] = r

    # Sort by started_at descending
    results = sorted(seen.values(), key=lambda r: r.started_at or "", reverse=True)
    return [r.to_dict() for r in results]


def list_test_results_by_definition(test_definition_id: str) -> List[Dict[str, Any]]:
    """List test runs across projects for a given test definition id."""
    projects_base = Path(settings.projects_dir)
    found: list[TestResult] = []

    for result_file in projects_base.rglob(".results/*.json"):
        try:
            data = json.loads(result_file.read_text(encoding="utf-8"))
            if data.get("definition_test_id") != test_definition_id:
                continue
            project_id = data.get("project_id") or result_file.parents[2].name
            r = _load_result_from_disk(project_id, result_file.stem)
            if r:
                found.append(r)
        except Exception:
            continue

    found.sort(key=lambda r: r.started_at or "", reverse=True)
    return [r.to_dict() for r in found]


def _parse_robot_output(output_xml: Path) -> List[Dict[str, Any]]:
    """Parse Robot Framework output.xml for test case results."""
    try:
        import xml.etree.ElementTree as ET
        tree = ET.parse(output_xml)
        root = tree.getroot()

        results = []
        for test in root.iter("test"):
            status_elem = test.find("status")
            results.append({
                "name": test.get("name", ""),
                "status": status_elem.get("status", "UNKNOWN") if status_elem is not None else "UNKNOWN",
                "start_time": status_elem.get("starttime", "") if status_elem is not None else "",
                "end_time": status_elem.get("endtime", "") if status_elem is not None else "",
                "message": (status_elem.text or "") if status_elem is not None else "",
            })
        return results
    except Exception as exc:
        logger.warning("Failed to parse Robot output: %s", exc)
        return []
