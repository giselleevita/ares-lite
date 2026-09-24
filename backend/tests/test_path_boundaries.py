from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from core.paths import resolve_under
from core.settings import settings
from main import _annotation_path_from_config, _run_dir
from pipeline.run import _resolve_external_predictions_path


def test_resolve_under_accepts_nested_relative_path(tmp_path: Path) -> None:
    assert resolve_under(tmp_path, "predictions", "model.json") == tmp_path / "predictions" / "model.json"


@pytest.mark.parametrize("untrusted", ["../secret.json", "nested/../../secret.json"])
def test_resolve_under_rejects_parent_traversal(tmp_path: Path, untrusted: str) -> None:
    with pytest.raises(ValueError, match="storage root"):
        resolve_under(tmp_path, untrusted)


def test_resolve_under_rejects_absolute_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="storage root"):
        resolve_under(tmp_path, tmp_path.parent / "secret.json")


def test_resolve_under_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="storage root"):
        resolve_under(root, "escape", "secret.json")


def test_run_dir_maps_unsafe_identifier_to_not_found(tmp_path: Path) -> None:
    old_runs_dir = settings.runs_dir
    try:
        settings.runs_dir = tmp_path / "runs"
        with pytest.raises(HTTPException) as exc:
            _run_dir("../other-run")
        assert exc.value.status_code == 404
    finally:
        settings.runs_dir = old_runs_dir


def test_annotation_path_rejects_escape(tmp_path: Path) -> None:
    old_data_dir = settings.data_dir
    try:
        settings.data_dir = tmp_path / "data"
        payload = {"scenario_snapshot": {"ground_truth": "../../secret.json"}}
        with pytest.raises(HTTPException) as exc:
            _annotation_path_from_config(payload)
        assert exc.value.status_code == 422
    finally:
        settings.data_dir = old_data_dir


def test_external_predictions_path_rejects_absolute_and_traversal(tmp_path: Path) -> None:
    old_data_dir = settings.data_dir
    try:
        settings.data_dir = tmp_path / "data"
        for unsafe in ("../secret.json", str(tmp_path / "secret.json")):
            with pytest.raises(HTTPException) as exc:
                _resolve_external_predictions_path(unsafe)
            assert exc.value.status_code == 422
    finally:
        settings.data_dir = old_data_dir
