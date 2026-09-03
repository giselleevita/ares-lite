from __future__ import annotations

import hashlib
import json
from zipfile import ZIP_DEFLATED, ZipFile

from reporting.verify import verify_evidence_pack


def _pack(path, payload: bytes = b"evidence") -> None:
    manifest = {"manifest_version": "1.0.0", "files": [{"path": "report.json", "sha256": hashlib.sha256(payload).hexdigest()}]}
    with ZipFile(path, "w", ZIP_DEFLATED) as bundle:
        bundle.writestr("report.json", payload)
        bundle.writestr("manifest.json", json.dumps(manifest))


def test_verifier_accepts_intact_pack(tmp_path) -> None:
    path = tmp_path / "evidence.zip"
    _pack(path)
    assert verify_evidence_pack(path)["valid"] is True


def test_verifier_rejects_tampering(tmp_path) -> None:
    path = tmp_path / "evidence.zip"
    _pack(path, b"tampered")
    with ZipFile(path, "a") as bundle:
        bundle.writestr("report.json", b"changed")
    result = verify_evidence_pack(path)
    assert result["valid"] is False
