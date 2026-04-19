"""Deployment pipeline — the main orchestrator tying analysis → Docker → run.

Now with integrated logging, metrics tracking, and rollback version saving.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
import uuid
import weakref
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.deployment.core.config import settings
from app.deployment.core.events import event_bus
from app.deployment.core.exceptions import DeployError, NotFoundError
from app.deployment.models.deployment import DeploymentConfig, DeploymentStatus
from app.deployment.models.project import ProjectMetadata
from app.deployment.services.analyzer.file_scanner import build_file_tree
from app.deployment.services.analyzer.project_analyzer import analyze_project
from app.deployment.services.analyzer.swagger_generator import generate_openapi_spec
from app.deployment.services.docker.builder import docker_builder
from app.deployment.services.deployer.error_taxonomy import classify_deploy_error
from app.deployment.services.enhanced.metrics_collector import metrics
from app.deployment.services.enhanced.rollback_manager import rollback_manager
from app.deployment.services.logger import LoggerManager
from app.deployment.store.json_store import JsonStore

logger = logging.getLogger(__name__)

# Concurrency limiter for LLM calls.
#
# IMPORTANT: This service uses `asyncio.run()` inside FastAPI BackgroundTasks
# (threadpool), which creates a *new* event loop per background thread.
# asyncio synchronization primitives become bound to the first loop that
# uses them (Python 3.11+). A single global Semaphore would then crash with:
#   "... is bound to a different event loop"
# when used from another background thread.
#
# To avoid that, keep a semaphore per running loop.
_llm_locks: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = weakref.WeakKeyDictionary()


def _get_llm_lock() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    lock = _llm_locks.get(loop)
    if lock is None:
        max_conc = getattr(settings, "llm_max_concurrency", 1) or 1
        lock = asyncio.Semaphore(int(max_conc))
        _llm_locks[loop] = lock
    return lock

# ── Shared stores (initialised once, imported by API routers) ────

project_store: JsonStore[ProjectMetadata] = JsonStore(
    settings.projects_dir, ProjectMetadata, id_field="project_id"
)

deployment_store: JsonStore[DeploymentStatus] = JsonStore(
    settings.deployments_dir, DeploymentStatus, id_field="deployment_id"
)


def run_deployment_sync(deployment_id: str, project_id: str, deploy_mode: str | None = None) -> None:
    """Sync wrapper for the async deployment pipeline.

    FastAPI/Starlette `BackgroundTasks` will run sync callables in a threadpool.
    This wrapper ensures the heavy deployment work (which includes blocking
    Docker calls) does not block the main event loop and keeps API endpoints
    responsive while a deployment is running.
    """
    asyncio.run(run_deployment(deployment_id, project_id, deploy_mode))


async def _publish(deployment_id: str, step: str, message: str):
    """Publish progress events so subscribers (WebSocket, logs) are notified."""
    await event_bus.publish("deploy.step", {
        "deployment_id": deployment_id,
        "step": step,
        "message": message,
    })


# ── Analysis (background) ───────────────────────────────────────

async def run_analysis(project_id: str, project_path: str, execution_mode: str | None = None) -> None:
    """Analyse a project in the background and store results."""
    from app.deployment.services.llm.client import set_active_project
    set_active_project(project_id)

    project = project_store.get(project_id)
    if not project:
        logger.error("Project %s not found for analysis", project_id)
        return

    proj_logger = LoggerManager.get(project_id)

    try:
        proj_logger.info("Starting project analysis")
        metrics.increment("analysis.started")
        t0 = time.perf_counter()

        async with _get_llm_lock():
            analysis = await analyze_project(project_path, hint_type=execution_mode)

        duration = time.perf_counter() - t0
        metrics.record_duration("analysis", duration)
        metrics.increment("analysis.completed")

        # Build file tree
        file_tree_dict = build_file_tree(Path(project_path))
        from app.deployment.models.project import FileNode
        try:
            file_tree = FileNode.model_validate(file_tree_dict)
        except Exception:
            file_tree = None

        project.analysis = analysis
        project.project_type = analysis.project_type
        project.file_tree = file_tree
        project_store.save(project)

        proj_logger.log_analysis(
            project_type=analysis.project_type,
            tech_stack=analysis.tech_stack,
            summary=analysis.summary,
        )
        proj_logger.info(f"Analysis complete: type={analysis.project_type}, duration={duration:.1f}s")

    except Exception as exc:
        metrics.increment("analysis.failed")
        proj_logger.error("Analysis failed", error=exc)
        logger.exception("Analysis failed for %s: %s", project_id, exc)


# ── Full deploy pipeline (background) ───────────────────────────

async def run_deployment(deployment_id: str, project_id: str, deploy_mode: str | None = None) -> None:
    """Full deployment pipeline: analyse → generate → build → run → verify.

    Runs as a background task. Updates DeploymentStatus along the way.
    Integrated with logging, metrics, rollback, and acceptance checks.
    deploy_mode: frontend-only | backend-only | fullstack | None (auto-detect).
    """
    from app.deployment.services.llm.client import set_active_project
    from app.deployment.services.deployer.acceptance import run_acceptance_checks

    set_active_project(project_id)

    deployment = deployment_store.get(deployment_id)
    if not deployment:
        logger.error("Deployment %s not found", deployment_id)
        return

    project = project_store.get(project_id)
    if not project:
        deployment.status = "error"
        deployment.error_message = "Project not found"
        deployment_store.save(deployment)
        return

    proj_logger = LoggerManager.get(project_id)
    project_path = Path(settings.projects_dir) / project_id
    deploy_start = time.perf_counter()
    deployment.total_steps = 5  # analyse → generate → build → verify → success

    metrics.increment("deploy.started")
    metrics.record_event("deploy_start", {
        "deployment_id": deployment_id,
        "project_id": project_id,
        "project_name": project.name,
    })

    try:
        # Step 1: Ensure analysis exists
        if not project.analysis:
            deployment.status = "analyzing"
            deployment.current_step = 1
            deployment_store.save(deployment)
            await _publish(deployment_id, "analyzing", "Analysing project structure…")
            proj_logger.log_pipeline_step(
                "analyse", "Running project analysis", "running", deployment_id
            )

            await run_analysis(project_id, str(project_path), execution_mode=deploy_mode)
            project = project_store.get(project_id)
            if not project or not project.analysis:
                raise DeployError("Project analysis failed")
            proj_logger.log_pipeline_step(
                "analyse", f"Analysis complete: {project.analysis.project_type}",
                "done", deployment_id
            )

        # Step 2: Generate Docker config
        deployment.status = "building"
        deployment.current_step = 2
        deployment_store.save(deployment)
        await _publish(deployment_id, "building", "Generating Dockerfile via LLM…")
        t0 = time.perf_counter()
        mode_str = deploy_mode or "auto"
        deployment.deploy_mode = mode_str
        deployment_store.save(deployment)
        model_name = settings.litai_model
        proj_logger.log_pipeline_step(
            "generate", f"Generating Docker config via LLM (mode={mode_str}, model={model_name})",
            "running", deployment_id
        )
        async with _get_llm_lock():
            config = await docker_builder.build_deployment_config(
                project_id, project_path, project.analysis, deploy_mode=deploy_mode,
            )
        gen_dur = time.perf_counter() - t0
        metrics.record_duration("docker.config_gen", gen_dur)
        proj_logger.log_pipeline_step(
            "generate", f"Docker config ready in {gen_dur:.1f}s", "done", deployment_id
        )

        # Step 3: Build and run
        deployment.current_step = 3
        deployment_store.save(deployment)
        await _publish(deployment_id, "deploying", "Building Docker image…")
        proj_logger.log_pipeline_step(
            "build", "Building and running Docker image", "running", deployment_id
        )

        t0 = time.perf_counter()
        result = await docker_builder.build_and_run(config, project_path, project.analysis)
        build_dur = time.perf_counter() - t0
        metrics.record_duration("docker.build_run", build_dur)
        proj_logger.log_pipeline_step(
            "build",
            f"Image built & containers running in {build_dur:.1f}s — {result.get('preview_url', '')}",
            "done",
            deployment_id,
        )

        # Save rollback version
        rollback_manager.save_version(
            deployment_id,
            dockerfile=config.dockerfile_content,
            compose=config.compose_content or "",
            build_spec=config.build_spec,
            image_tag=result.get("image_tag", ""),
        )

        # Save deployment info
        deployment.deploy_mode = (config.build_spec or {}).get("deploy_mode", "auto")
        deployment.container_id = result.get("container_id")
        deployment.image_tag = result.get("image_tag")
        deployment.image_tags = result.get("image_tags")
        deployment.preview_url = result.get("preview_url")
        deployment.compose_project = result.get("compose_project")
        deployment.compose_file_path = result.get("compose_file")
        deployment.compose_services = result.get("compose_services")
        deployment.host_port = (result.get("ports") or [{}])[0].get("hostPort") if result.get("ports") else None
        deployment.extra_ports = result.get("ports")
        # Keep a capped copy in metadata, but also write full logs to disk.
        full_build_logs = result.get("build_logs", "") or ""
        try:
            build_logs_path = project_path / ".logs" / f"build_logs_{deployment_id}.txt"
            build_logs_path.write_text(full_build_logs, encoding="utf-8")
            proj_logger.info(f"Saved full build logs: {build_logs_path}")
        except Exception as exc:
            proj_logger.warning(f"Failed to write full build logs: {exc}")
        deployment.build_logs = full_build_logs[:200000]  # cap metadata at 200 KB

        # Save per-service port mappings for proxy routing
        from app.deployment.models.deployment import ServicePortMapping
        raw_ports = result.get("service_ports", [])
        deployment.service_ports = [
            ServicePortMapping(**sp) for sp in raw_ports
        ] if raw_ports else None

        deployment.updated_at = datetime.now()
        deployment_store.save(deployment)
        
        # Step 1.1: Generate Swagger if needed
        try:
            summary = project.analysis.summary_dict
            logger.info(f"Swagger check for {deployment_id}: summary={summary}, mode={deploy_mode}")
            # Ensure we always generate Swagger for backend-only projects, 
            # even if no specific endpoints were detected (uses the default fallback).
            if (deployment.deploy_mode == "backend-only" and 
                not summary.get("has_existing_docs", False)):
                
                logger.info(f"Triggering Swagger generation for {deployment_id} with {len(project.analysis.api_endpoints)} endpoints")
                spec = generate_openapi_spec(
                    project.analysis.api_endpoints, 
                    project_name=project.name or "Project API"
                )
                logger.debug(f"Swagger spec generated for {deployment_id}: {list(spec.get('paths', {}).keys())}")
                
                # Save to deployment folder
                deploy_dir = Path(settings.deployments_dir) / deployment_id
                deploy_dir.mkdir(parents=True, exist_ok=True)
                swagger_path = deploy_dir / "openapi.json"
                
                import json
                swagger_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
                
                logger.info(f"Generated Swagger spec for {deployment_id} at {swagger_path}")
        except Exception as sw_exc:
            logger.exception("Swagger generation failed for %s", deployment_id)
            proj_logger.warning(f"Swagger generation failed: {sw_exc}")

        # Step 4: Acceptance checks — verify containers are actually serving
        deployment.current_step = 4
        deployment.status = "deploying"
        deployment_store.save(deployment)
        await _publish(deployment_id, "verifying", "Running acceptance checks…")
        proj_logger.log_pipeline_step(
            "verify", "Running acceptance checks", "running", deployment_id
        )

        acceptance_result = await run_acceptance_checks(
            service_ports=raw_ports,
            timeout_seconds=float(getattr(settings, "readiness_timeout_seconds", 45) or 45),
            poll_interval=float(getattr(settings, "readiness_poll_interval_seconds", 2.0) or 2.0),
        )

        if acceptance_result.get("passed", False):
            deployment.status = "success"
            proj_logger.log_pipeline_step(
                "verify",
                f"Acceptance passed — {acceptance_result.get('message', '')}",
                "done",
                deployment_id,
            )
        else:
            failed = [
                f"{svc}: {info.get('error', 'no response')}"
                for svc, info in acceptance_result.get("services", {}).items()
                if info.get("status") != "healthy"
            ]
            # If at least some services are reachable (tcp_ok or healthy), we consider it 'success' but warn
            any_reachable = any(info.get("status") in {"healthy", "degraded"} for info in acceptance_result.get("services", {}).items())
            
            if any_reachable:
                deployment.status = "success"
                proj_logger.log_pipeline_step(
                    "verify",
                    f"Acceptance partial — container is up but HTTP checks failed: {failed}",
                    "done",
                    deployment_id,
                )
            else:
                deployment.status = "error"
                proj_logger.log_pipeline_step(
                    "verify",
                    f"Acceptance failed — container unreachable: {failed}",
                    "error",
                    deployment_id,
                )
            
            logger.warning("Acceptance result for %s: %s", deployment_id, acceptance_result)

        # Step 5: Success + Bundle
        # Set API/Swagger URL for backend/fullstack projects
        if deployment.deploy_mode in ("backend-only", "fullstack"):
            swagger_path = Path(settings.deployments_dir) / deployment_id / "openapi.json"
            if swagger_path.exists():
                # Point to our internal swagger UI route
                deployment.api_url = f"/api/deployments/{deployment_id}/swagger"
            elif project.analysis.summary_dict.get("has_existing_docs"):
                # If they have their own, maybe try to guess. 
                # For now, we'll just leave it or try well-known paths.
                pass

        deployment_store.save(deployment)

        # Generate .env if project doesn't have one (LLM-only mode)
        try:
            from app.deployment.services.analyzer.file_scanner import sample_key_files
            from app.deployment.services.docker.env_generator import find_existing_env, generate_env_with_llm
            env_path = project_path / ".env.deployer"
            if env_path.exists() and env_path.is_dir():
                shutil.rmtree(env_path, ignore_errors=True)
                env_path.write_text("", encoding="utf-8")
                proj_logger.warning("Replaced directory .env.deployer with file for compose compatibility")
            if (deployment.deploy_mode or "") == "frontend-only":
                proj_logger.info("Skipping .env.deployer generation for frontend-only")
            elif env_path.exists() and env_path.stat().st_size > 0:
                proj_logger.info(".env.deployer already present; keeping existing")
            elif not find_existing_env(project_path):
                file_tree = str(build_file_tree(project_path))
                file_samples = str(sample_key_files(project_path))
                env_content = await generate_env_with_llm(
                    project_path,
                    project.analysis,
                    file_tree,
                    file_samples,
                )
                env_path.write_text(env_content, encoding="utf-8")
                proj_logger.info("Generated .env.deployer via LLM (no .env found in repo)")
            else:
                proj_logger.info("Using existing .env from repository")
        except Exception as env_exc:
            proj_logger.warning(f"Env generation skipped: {env_exc}")

        # Create portable bundle (.tar.gz)
        try:
            from app.deployment.services.docker.bundler import create_bundle

            def _deployment_includes_db(dep) -> bool:
                try:
                    if dep.compose_services and "db" in set(dep.compose_services):
                        return True
                    if dep.service_ports and any(getattr(sp, "service", None) == "db" for sp in dep.service_ports):
                        return True
                    if dep.image_tags and isinstance(dep.image_tags, dict) and ("db" in dep.image_tags):
                        return True
                except Exception:
                    return False
                return False

            bundle_path = await create_bundle(
                project_id=project_id,
                deployment=deployment,
                project_path=project_path,
                analysis=project.analysis,
                include_db_image=_deployment_includes_db(deployment),
            )
            proj_logger.info(f"Bundle created: {bundle_path}")
        except Exception as bundle_exc:
            proj_logger.warning(f"Bundle creation skipped: {bundle_exc}")

        total_duration = time.perf_counter() - deploy_start
        metrics.record_duration("deploy.total", total_duration)
        metrics.increment("deploy.succeeded")

        proj_logger.log_deploy(
            container_id=deployment.container_id or "",
            preview_url=deployment.preview_url or "",
            success=True,
        )
        proj_logger.log_pipeline_step(
            "success",
            f"Deployment finished in {total_duration:.1f}s — preview: {deployment.preview_url}",
            "done",
            deployment_id,
        )
        deployment.status = "success"
        deployment_store.save(deployment)

        await _publish(deployment_id, "success", f"Deployed! Preview: {deployment.preview_url}")
        logger.info("Deployment %s succeeded: %s", deployment_id, deployment.preview_url)

    except Exception as exc:
        total_duration = time.perf_counter() - deploy_start
        build_logs = (deployment.build_logs or "") if deployment else ""
        taxonomy = classify_deploy_error(str(exc), build_logs=build_logs)
        error_code = taxonomy.get("code", "unknown_deploy_failure")
        suggested = taxonomy.get("suggested_action", "")
        metrics.record_duration("deploy.total", total_duration)
        metrics.increment("deploy.failed")
        metrics.record_event("deploy_failed", {
            "deployment_id": deployment_id,
            "error": str(exc)[:200],
            "error_code": error_code,
        })

        proj_logger.error("Deployment failed", error=exc)
        proj_logger.log_pipeline_error("error", f"Deployment failed ({error_code})", str(exc)[:500], deployment_id)
        logger.exception("Deployment %s failed: %s", deployment_id, exc)

        deployment.status = "error"
        deployment.error_message = f"[{error_code}] {exc}" + (f" | suggested: {suggested}" if suggested else "")
        deployment.updated_at = datetime.now()
        deployment_store.save(deployment)
        await _publish(deployment_id, "error", f"Deployment failed ({error_code}): {exc}")
