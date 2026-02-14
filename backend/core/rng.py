from __future__ import annotations

import secrets


def choose_seed(requested_seed: int | None) -> tuple[int, bool]:
    """Return (seed_used, deterministic).

    If requested_seed is None, we intentionally choose a fresh random seed to
    preserve non-deterministic behavior by default.
    """
    if requested_seed is None:
        return secrets.randbelow(2_147_483_647), False
    return int(requested_seed), True

