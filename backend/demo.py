from __future__ import annotations

from db.session import SessionLocal, init_db
from pipeline.orchestrator import execute_run


def main() -> None:
    print("ARES Lite deterministic demo run")
    init_db()

    common_options = {
        "resize": 640,
        "every_n_frames": 2,
        "max_frames": 120,
        "seed": 1337,
    }

    with SessionLocal() as db:
        baseline_result = execute_run(
            db=db,
            scenario_id="urban_dusk",
            options={**common_options, "disable_stress": True},
        )
        stressed_result = execute_run(
            db=db,
            scenario_id="urban_dusk",
            options={**common_options, "disable_stress": False},
        )

    readiness_score = stressed_result["readiness"].get("readiness_score", 0.0)
    recommendation = stressed_result["readiness"].get("recommendation", "UNKNOWN")
    degradation_present = bool(stressed_result["reliability_metrics"].get("degradation_delta"))
    report_path = stressed_result["report_paths"]["latest_report_path"]

    print(f"baseline run: {baseline_result['run_id']}")
    print(f"stressed run: {stressed_result['run_id']}")
    print(f"urban_dusk readiness: {readiness_score} ({recommendation})")
    print(f"degradation observed under stress: {'yes' if degradation_present else 'no'}")
    print(f"report generated at: {report_path}")


if __name__ == "__main__":
    main()
