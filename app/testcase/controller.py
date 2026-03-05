"""Testing API — prompt-based test generation and execution."""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict
from typing import Optional
import httpx

from app.deployment.core.config import settings
from app.testcase.models.testcase import TestDefinition
from app.deployment.services.deployer.pipeline import project_store, deployment_store
from app.testcase.services.generator import generate_test_cases, generate_robot_suite_content
from app.testcase.services.runner import (
    run_robot_tests_with_suite_content,
    get_test_result,
    list_test_results_by_definition,
)
from app.deployment.store.json_store import JsonStore

router = APIRouter(prefix="/api/tests", tags=["Testing"])

test_definition_store: JsonStore[TestDefinition] = JsonStore(
    str(Path(settings.data_dir) / "tests"),
    TestDefinition,
    id_field="test_id",
)


class TestDefinitionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str


class TestSuiteUpdateRequest(BaseModel):
    content: str


class TestRunRequest(BaseModel):
    project_id: str
    preview_url: Optional[str] = None


def _find_preview_url_for_project(project_id: str) -> str:
    for dep in deployment_store.list_all():
        if dep.project_id == project_id and dep.preview_url:
            return dep.preview_url
    return ""


def _save_definition_robot_file(test_id: str, suite_content: str) -> str:
    suites_dir = Path(settings.data_dir) / "tests" / "suites"
    suites_dir.mkdir(parents=True, exist_ok=True)
    suite_file = suites_dir / f"{test_id}.robot"
    suite_file.write_text(suite_content, encoding="utf-8")
    return str(suite_file)


@router.post("/generate")
@router.post("/definitions/generate")
async def create_test_definition(body: TestDefinitionCreateRequest):
    """Create a reusable test definition from prompt (test_id-first)."""
    project_type = "unknown"
    tech_stack = []
    preview_url = ""

    test_id = str(uuid.uuid4())
    context_id = f"test-{test_id}"

    test_cases = await generate_test_cases(
        project_id=context_id,
        user_prompt=body.prompt,
        project_type=project_type,
        tech_stack=tech_stack,
        preview_url=preview_url,
    )
    suite_content = await generate_robot_suite_content(
        context_id=context_id,
        user_prompt=body.prompt,
        project_type=project_type,
        tech_stack=tech_stack,
        preview_url=preview_url,
    )

    definition = TestDefinition(
        test_id=test_id,
        prompt=body.prompt,
        suite_content=suite_content,
        version=1,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        project_context_id=None,
        preview_url_hint=preview_url or None,
        project_type_hint=project_type,
        tech_stack_hint=tech_stack,
        latest_test_cases=test_cases,
    )
    test_definition_store.save(definition)
    robot_file = _save_definition_robot_file(test_id, suite_content)

    return {
        "test_id": test_id,
        "version": definition.version,
        "test_cases": test_cases,
        "suite_content": suite_content,
        "suite_file": robot_file,
    }


@router.get("/definitions/{test_id}")
async def get_test_definition(test_id: str):
    definition = test_definition_store.get(test_id)
    if not definition:
        raise HTTPException(status_code=404, detail="Test definition not found")
    return definition.model_dump(mode="json")


@router.get("/definitions/{test_id}/suite")
async def get_test_definition_suite(test_id: str):
    definition = test_definition_store.get(test_id)
    if not definition:
        raise HTTPException(status_code=404, detail="Test definition not found")
    return {
        "test_id": definition.test_id,
        "version": definition.version,
        "suite_content": definition.suite_content,
    }


@router.put("/definitions/{test_id}/suite")
async def update_test_definition_suite(test_id: str, body: TestSuiteUpdateRequest):
    definition = test_definition_store.get(test_id)
    if not definition:
        raise HTTPException(status_code=404, detail="Test definition not found")
    if not body.content:
        raise HTTPException(status_code=400, detail="content is required")

    definition.suite_content = body.content
    definition.version += 1
    definition.updated_at = datetime.now()
    test_definition_store.save(definition)
    robot_file = _save_definition_robot_file(definition.test_id, definition.suite_content)

    return {
        "test_id": definition.test_id,
        "version": definition.version,
        "message": "Suite updated",
        "suite_file": robot_file,
    }


@router.post("/definitions/{test_id}/run")
async def run_test_definition(test_id: str, body: TestRunRequest):
    definition = test_definition_store.get(test_id)
    if not definition:
        raise HTTPException(status_code=404, detail="Test definition not found")
    project = project_store.get(body.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    preview_url = body.preview_url or _find_preview_url_for_project(body.project_id)
    suite_content = definition.suite_content
    if preview_url:
        suite_content = suite_content.replace("http://localhost:3000", preview_url.rstrip("/"))

    result = await run_robot_tests_with_suite_content(
        body.project_id,
        suite_content,
        definition_test_id=test_id,
        suite_version=definition.version,
    )
    payload = result.to_dict()
    payload["test_id"] = test_id
    payload["run_id"] = result.test_id
    payload["project_id"] = body.project_id
    return payload


@router.get("/definitions/{test_id}/runs")
async def list_runs_for_test_definition(test_id: str):
    if not test_definition_store.exists(test_id):
        raise HTTPException(status_code=404, detail="Test definition not found")
    return list_test_results_by_definition(test_id)


@router.get("/runs/{run_id}")
async def get_test_run(run_id: str):
    result = get_test_result(run_id)
    if not result:
        raise HTTPException(status_code=404, detail="Test run not found")
    return result.to_dict()


def _extract_legacy_endpoints(project_id: str) -> list[dict]:
    project = project_store.get(project_id)
    if not project or not project.analysis:
        return []
    backend_info = project.analysis.backend_info or {}
    raw = backend_info.get("api_endpoints") or []
    out: list[dict] = []
    if isinstance(raw, list):
        for idx, item in enumerate(raw):
            if isinstance(item, dict):
                method = str(item.get("method") or "GET").upper()
                path = str(item.get("path") or item.get("url") or "/")
            else:
                text = str(item)
                parts = text.split(maxsplit=1)
                method = parts[0].upper() if parts and parts[0].isalpha() and len(parts[0]) <= 8 else "GET"
                path = parts[1] if len(parts) > 1 else text
                if not path.startswith("/"):
                    path = f"/{path}"
            out.append({
                "id": f"ep-{idx + 1}",
                "method": method,
                "path": path,
                "description": "",
                "parameters": [],
            })
    return out


def _find_preview_url(project_id: str) -> str:
    for dep in deployment_store.list_all():
        if dep.project_id == project_id and dep.preview_url:
            return dep.preview_url
    return ""


@router.get("/api/{project_id}/endpoints")
async def get_api_endpoints_legacy(project_id: str):
    """Legacy endpoint: list API endpoints discovered from analysis."""
    return _extract_legacy_endpoints(project_id)


@router.post("/api/{project_id}/endpoints/{endpoint_id:path}/test")
async def test_api_endpoint_legacy(project_id: str, endpoint_id: str, payload: dict):
    """Legacy endpoint: send an HTTP request to preview URL using provided parameters."""
    endpoints = _extract_legacy_endpoints(project_id)
    endpoint = next((ep for ep in endpoints if ep["id"] == endpoint_id), None)
    if endpoint is None:
        raise HTTPException(status_code=404, detail="Endpoint not found")

    base_url = _find_preview_url(project_id)
    if not base_url:
        raise HTTPException(status_code=400, detail="Project has no active preview URL")

    method = endpoint.get("method", "GET").upper()
    path = payload.get("resolvedPath") or endpoint.get("path") or "/"
    if not str(path).startswith("/"):
        path = f"/{path}"
    target = f"{base_url.rstrip('/')}{path}"
    query = payload.get("query") if isinstance(payload.get("query"), dict) else {}
    headers = payload.get("headers") if isinstance(payload.get("headers"), dict) else {}
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}

    started = httpx.Timeout(20.0)
    try:
        async with httpx.AsyncClient(timeout=started) as client:
            response = await client.request(
                method=method,
                url=target,
                params=query,
                headers=headers,
                json=body if method in {"POST", "PUT", "PATCH", "DELETE"} else None,
            )
        response_data = None
        try:
            response_data = response.json()
        except Exception:
            response_data = response.text
        return {
            "endpointId": endpoint_id,
            "status": "success" if response.status_code < 500 else "error",
            "statusCode": response.status_code,
            "responseTime": 0,
            "response": response_data,
        }
    except Exception as exc:
        return {
            "endpointId": endpoint_id,
            "status": "error",
            "statusCode": 0,
            "responseTime": 0,
            "response": None,
            "error": str(exc),
        }
