"""Errors raised by the business layer. Each carries a stable machine-readable code."""

from __future__ import annotations


class BusinessError(Exception):
    """A failure the caller can understand and act on (bad input, unknown id, conflict)."""

    code = "error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class InvalidInput(BusinessError):
    code = "invalid_input"


class NotFound(BusinessError):
    code = "not_found"


class Conflict(BusinessError):
    code = "conflict"
