from metrics.reliability import compute_reliability_metrics, iou


def test_iou_overlap() -> None:
    score = iou([10, 10, 20, 20], [20, 20, 20, 20])
    assert round(score, 4) == 0.1429


def test_iou_no_overlap() -> None:
    assert iou([0, 0, 10, 10], [20, 20, 5, 5]) == 0.0


def test_compute_reliability_metrics_basic() -> None:
    detections = {
        0: [{"bbox": [10, 10, 10, 10], "confidence": 0.9}],
        1: [{"bbox": [40, 40, 8, 8], "confidence": 0.8}],
        2: [],
    }
    ground_truth = {
        0: [{"bbox": [11, 11, 10, 10], "label": "drone"}],
        1: [],
        2: [{"bbox": [25, 25, 6, 6], "label": "drone"}],
    }
    payload = compute_reliability_metrics(
        detections_by_frame=detections,
        ground_truth_by_frame=ground_truth,
        frame_indices=[0, 1, 2],
        fps=15.0,
    )

    assert payload["precision"] == 0.5
    assert payload["recall"] == 0.5
    assert payload["false_negative_frames"]["count"] == 1
    assert payload["false_negative_frames"]["frames"] == [2]
    assert payload["detection_delay_seconds"] == 0.0
