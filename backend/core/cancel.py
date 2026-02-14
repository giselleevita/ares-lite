from __future__ import annotations


class CancelledRun(RuntimeError):
    """Raised to cooperatively stop a run when cancellation is requested."""

