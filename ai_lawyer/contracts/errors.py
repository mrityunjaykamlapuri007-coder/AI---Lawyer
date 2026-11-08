"""Typed error objects.  Client responses never contain stack traces."""
from __future__ import annotations

from typing import Any


class UserSafeError(Exception):
    def __init__(
        self,
        error_code: str,
        user_safe_message: str,
        *,
        retryable: bool = False,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(user_safe_message)
        self.error_code = error_code
        self.user_safe_message = user_safe_message
        self.retryable = retryable
        self.status_code = status_code
        self.details = details or {}


class CorpusValidationError(UserSafeError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__(
            "corpus_invalid",
            "The legal corpus failed validation. The application cannot give a "
            "supported answer until the corpus is fixed.",
            retryable=False,
            status_code=500,
            details={"errors": errors},
        )
        self.errors = errors


class IndexStale(UserSafeError):
    def __init__(self, detail: str = "") -> None:
        super().__init__(
            "index_stale",
            "The search index is out of date. Rebuild it before searching.",
            retryable=True,
            status_code=503,
            details={"detail": detail},
        )


class ModelOutputInvalid(UserSafeError):
    def __init__(self, detail: str = "") -> None:
        super().__init__(
            "model_output_invalid",
            "The language model returned an unusable response. Please try again.",
            retryable=True,
            status_code=502,
            details={"detail": detail},
        )


class NotConfigured(UserSafeError):
    def __init__(self, what: str) -> None:
        super().__init__(
            "not_configured",
            f"{what} is not configured for this deployment.",
            retryable=False,
            status_code=503,
        )
