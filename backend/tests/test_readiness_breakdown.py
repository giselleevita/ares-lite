from __future__ import annotations

from metrics.readiness import compute_readiness


def test_readiness_breakdown_schema_and_math() -> None:
    metrics_payload = {
        "precision": 0.8,
        "recall": 0.6,
        "track_stability_index": 0.75,
        "detection_delay_seconds": 1.5,
        "false_positive_rate_per_minute": 0.2,
        "baseline_missing": True,
        "degradation_delta": None,
    }
    engagement_payload = {
        "engagement_success_rate": 0.7,
        "waste_rate": 0.1,
    }

    readiness = compute_readiness(metrics_payload, engagement_payload, stress_enabled=True)
    assert "readiness_score" in readiness
    assert "readiness_breakdown" in readiness
    rb = readiness["readiness_breakdown"]
    assert isinstance(rb, dict)
    assert set(rb.keys()) >= {
        "weighting_mode",
        "components",
        "top_positive_contributors",
        "top_negative_contributors",
    }

    components = rb["components"]
    assert isinstance(components, list)
    assert len(components) >= 4

    weights_sum = 0.0
    for c in components:
        assert isinstance(c, dict)
        assert set(c.keys()) >= {"name", "raw_value", "normalized_value", "weight", "contribution"}
        w = float(c["weight"])
        nv = float(c["normalized_value"])
        contrib = float(c["contribution"])
        weights_sum += w
        # Contribution must reflect the internal formula.
        assert abs(contrib - (nv * w)) <= 1e-6

    assert abs(weights_sum - 1.0) <= 1e-3

    top_pos = rb["top_positive_contributors"]
    top_neg = rb["top_negative_contributors"]
    assert isinstance(top_pos, list)
    assert isinstance(top_neg, list)
    assert len(top_pos) <= 3
    assert len(top_neg) <= 3

    # Ensure sorted by contribution.
    pos_contribs = [float(item["contribution"]) for item in top_pos]
    assert pos_contribs == sorted(pos_contribs, reverse=True)
    neg_contribs = [float(item["contribution"]) for item in top_neg]
    assert neg_contribs == sorted(neg_contribs)

