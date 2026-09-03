from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import BadZipFile, ZipFile


def verify_evidence_pack(path: str | Path) -> dict[str, object]:
    """Verify every file declared in an ARES evidence-pack manifest."""
    archive = Path(path)
    errors: list[str] = []
    try:
        with ZipFile(archive) as bundle:
            names = set(bundle.namelist())
            if "manifest.json" not in names:
                return {"valid": False, "errors": ["manifest.json is missing"]}
            manifest = json.loads(bundle.read("manifest.json"))
            files = manifest.get("files")
            if not isinstance(files, list):
                return {"valid": False, "errors": ["manifest files must be a list"]}
            declared: set[str] = set()
            for item in files:
                if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                    errors.append("invalid manifest file entry")
                    continue
                file_path = item["path"]
                declared.add(file_path)
                if file_path not in names:
                    errors.append(f"missing file: {file_path}")
                    continue
                actual = hashlib.sha256(bundle.read(file_path)).hexdigest()
                if actual != item.get("sha256"):
                    errors.append(f"hash mismatch: {file_path}")
            unexpected = names - declared - {"manifest.json"}
            if unexpected:
                errors.append("undeclared files: " + ", ".join(sorted(unexpected)))
    except (BadZipFile, OSError, json.JSONDecodeError) as exc:
        errors.append(f"invalid evidence pack: {exc}")
    return {"valid": not errors, "errors": errors}
