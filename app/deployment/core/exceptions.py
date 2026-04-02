"""Application-wide exception hierarchy.

Every custom exception carries an HTTP status_code so the global
exception handler in main.py can translate it automatically.
"""


class AppError(Exception):
    """Base for all application errors."""

    status_code: int = 500

    def __init__(self, message: str = "Internal server error", *, status_code: int | None = None):
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code


class LLMError(AppError):
    """Lightning AI / LLM communication failure."""

    status_code = 502


class AnalysisError(AppError):
    """Project analysis failed."""

    status_code = 422


class DockerError(AppError):
    """Docker build / runtime failure."""

    status_code = 500


class DeployError(AppError):
    """Deployment orchestration failure."""

    status_code = 500


class NotFoundError(AppError):
    """Resource not found."""

    status_code = 404
