"""Application configuration — loaded from .env via pydantic-settings."""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


# config.py lives at:  <repo_root>/app/deployment/core/config.py
# parents[0] = core/
# parents[1] = deployment/
# parents[2] = app/
# parents[3] = <repo_root>  ← workdir inside Docker (/app)
_BASE_DIR = Path(__file__).resolve().parents[3]

# .env lives at <repo_root>/.env  (same level as docker-compose.yml)
_ENV_FILE = _BASE_DIR / ".env"


class Settings(BaseSettings):
    # ── Lightning AI ──────────────────────────────────────────────
    litai_api_key: str = ""
    litai_model: str = "lightning-ai/DeepSeek-V3.1"
    litai_api_url: str = "https://lightning.ai/api/v1/chat/completions"

    # ── LLM behaviour ────────────────────────────────────────────
    llm_timeout_seconds: int = 300
    llm_max_output_tokens: int = 8000
    llm_max_retries: int = 5
    llm_retry_backoff: float = 3.0
    llm_max_concurrency: int = 1
    llm_advisory_only: bool = False

    # ── Server ───────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000
    public_base_url: str = ""

    # ── Storage dirs ─────────────────────────────────────────────
    data_dir: str = "./data"
    projects_dir: str = "./data/projects"
    deployments_dir: str = "./data/deployments"
    host_data_dir: str = ""
    submissions_dir: str = "/app/data/submissions"

    # ── Docker ───────────────────────────────────────────────────
    base_preview_port: int = 3000
    docker_network: str = "deployer-shared"
    max_repair_attempts: int = 2
    docker_build_timeout_seconds: int = 1200
    deploy_auto_adapt_files: bool = True

    # ── Runtime DB behaviour ─────────────────────────────────────
    # When true, database containers use tmpfs for their data dir, so
    # data resets every time the container stops/starts.
    db_ephemeral_default: bool = True
    # tmpfs size string understood by Docker (e.g. "512m", "1g").
    db_tmpfs_size: str = "512m"
    readiness_timeout_seconds: int = 45
    readiness_poll_interval_seconds: float = 2.0
    readiness_probe_paths: str = "/health,/healthz,/api/health,/status,/ping,/api,/"
    preview_ttl_seconds: int = 5 * 60
    stopped_deployment_cleanup_delay_seconds: int = 10 * 60
    # Auto-stop delay after submission pipeline finishes or container is activated
    container_auto_stop_delay_seconds: int = 5 * 60

    # ── Bundles ─────────────────────────────────────────────────
    # If false, bundle creation will NOT pull missing DB base images.
    # This helps ensure the resulting .tar.gz is truly self-contained.
    bundle_allow_pull_db_image: bool = False

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()

# Resolve relative paths against repo root (workdir = /app inside Docker)
for attr in ("data_dir", "projects_dir", "deployments_dir"):
    p = Path(getattr(settings, attr))
    if not p.is_absolute():
        setattr(settings, attr, str((_BASE_DIR / p).resolve()))


# Ensure directories exist
for d in (settings.data_dir, settings.projects_dir, settings.deployments_dir):
    Path(d).mkdir(parents=True, exist_ok=True)
