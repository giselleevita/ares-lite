from __future__ import annotations

from os import PathLike
from pathlib import Path


def resolve_under(root: str | PathLike[str], *parts: str | PathLike[str]) -> Path:
    """Resolve a path and require it to remain below ``root``.

    Resolving both paths also prevents an existing symlink within the requested
    path from escaping the configured storage root.
    """
    try:
        base = Path(root).resolve(strict=False)
        candidate = base.joinpath(*(Path(part) for part in parts)).resolve(strict=False)
        candidate.relative_to(base)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("Path escapes the configured storage root") from exc
    return candidate
