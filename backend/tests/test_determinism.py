from __future__ import annotations

import numpy as np

from simulation.stressors import StressApplier


def test_stressor_determinism_same_seed_same_output() -> None:
    image = np.full((32, 32, 3), 120, dtype=np.uint8)
    scenario = {
        "stressors": ["gaussian_noise"],
        "params": {"gaussian_noise": {"sigma": 9.0}},
    }

    a1 = StressApplier(scenario_config=scenario, seed=12345)
    a2 = StressApplier(scenario_config=scenario, seed=12345)

    out1 = a1.apply(frame_idx=0, image=image, sequence_idx=0).image
    out2 = a2.apply(frame_idx=0, image=image, sequence_idx=0).image

    assert np.array_equal(out1, out2)


def test_stressor_determinism_different_seed_different_output() -> None:
    image = np.full((32, 32, 3), 120, dtype=np.uint8)
    scenario = {
        "stressors": ["gaussian_noise"],
        "params": {"gaussian_noise": {"sigma": 9.0}},
    }

    a1 = StressApplier(scenario_config=scenario, seed=111)
    a2 = StressApplier(scenario_config=scenario, seed=222)

    out1 = a1.apply(frame_idx=0, image=image, sequence_idx=0).image
    out2 = a2.apply(frame_idx=0, image=image, sequence_idx=0).image

    assert not np.array_equal(out1, out2)

