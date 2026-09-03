#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from reporting.verify import verify_evidence_pack  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify an ARES Lite evidence pack")
    parser.add_argument("pack", type=Path)
    result = verify_evidence_pack(parser.parse_args().pack)
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
