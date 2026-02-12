from metrics.readiness import compute_readiness


def test_readiness_scoring_ready() -> None:
    metrics = {
        "precision": 0.9,
        "recall": 0.88,
        "track_stability_index": 0.86,
        "detection_delay_seconds": 0.6,
        "false_positive_rate_per_minute": 0.15,
        "degradation_delta": {"precision_delta": -0.02, "recall_delta": -0.03, "stability_delta": -0.01},
    }
    engagement = {
        "engagement_success_rate": 0.9,
        "waste_rate": 0.05,
    }
    payload = compute_readiness(metrics, engagement, stress_enabled=True)
    assert payload["readiness_score"] >= 75
    assert payload["recommendation"] == "READY"


def test_readiness_scoring_not_ready() -> None:
    metrics = {
        "precision": 0.2,
        "recall": 0.25,
        "track_stability_index": 0.1,
        "detection_delay_seconds": 6.0,
        "false_positive_rate_per_minute": 2.5,
        "degradation_delta": {"precision_delta": -0.2, "recall_delta": -0.25, "stability_delta": -0.2},
    }
    engagement = {
        "engagement_success_rate": 0.15,
        "waste_rate": 0.65,
    }
    payload = compute_readiness(metrics, engagement, stress_enabled=True)
    assert payload["readiness_score"] < 50
    assert payload["recommendation"] == "NOT_READY"
