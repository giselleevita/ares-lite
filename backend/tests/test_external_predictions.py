from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from pipeline.run import _load_external_detector_result


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_external_predictions_supports_frame_index_mapping(tmp_path: Path) -> None:
    path = _write_json(
        tmp_path / "pred_map.json",
        {
            "backend": "competitor_x",
            "detections_by_frame": {
                "0": [{"bbox": [1, 2, 3, 4], "confidence": 0.9, "label": "drone"}],
                "4": [{"bbox": [5, 6, 7, 8], "confidence": 0.8, "label": "drone"}],
            },
        },
    )
    result = _load_external_detector_result(path, frame_indices=[0, 2, 4])
    assert result.backend == "external:competitor_x"
    assert len(result.frame_boxes) == 3
    assert len(result.frame_boxes[0]) == 1
    assert result.frame_boxes[1] == []
    assert len(result.frame_boxes[2]) == 1


def test_external_predictions_supports_sequence_frame_boxes(tmp_path: Path) -> None:
    path = _write_json(
        tmp_path / "pred_seq.json",
        {
            "backend": "seq_model",
            "frame_boxes": [
                [{"bbox": [1, 1, 2, 2], "confidence": 0.7, "label": "drone"}],
                [],
            ],
        },
    )
    result = _load_external_detector_result(path, frame_indices=[10, 12])
    assert result.backend == "external:seq_model"
    assert len(result.frame_boxes) == 2
    assert len(result.frame_boxes[0]) == 1
    assert result.frame_boxes[1] == []


def test_external_predictions_rejects_length_mismatch(tmp_path: Path) -> None:
    path = _write_json(
        tmp_path / "pred_bad_len.json",
        {
            "frame_boxes": [
                [],
            ]
        },
    )
    with pytest.raises(HTTPException) as exc:
        _load_external_detector_result(path, frame_indices=[0, 2])
    assert exc.value.status_code == 422
    assert "length mismatch" in str(exc.value.detail)
