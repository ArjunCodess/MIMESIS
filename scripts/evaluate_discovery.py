"""Publish controls, spatial partitions and measured warm API latency."""

import json
from pathlib import Path
import platform
import statistics
import sys
import time
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.api.main import app, bundle, discovery

ROOT = Path(__file__).resolve().parents[1]


def evaluate():
    data = discovery()
    controls = []
    for task_id, task_runs in data["runs"].items():
        for tid, tiers in task_runs.items():
            rows = tiers["500"]["candidates"]
            worst = max(rows, key=lambda r: r["robust_loss"])
            controls.append(
                {
                    "task_id": task_id,
                    "target_id": tid,
                    "control_type": "measured_mismatch_diagnostic",
                    "candidate_id": worst["id"],
                    "robust_loss": worst["robust_loss"],
                    "rejected_by_frozen_cutoff": not worst[
                        "passes_provisional_threshold"
                    ],
                    "interpretation": "Deliberately selected worst measured mismatch, not an independently labelled geological negative",
                }
            )
    blocks = []
    for region in data["regions"]:
        candidates = [c for c in data["candidates"] if c["region_id"] == region["id"]]
        development = [c["id"] for c in candidates if c["easting_m"] <= -40000]
        held = [c["id"] for c in candidates if c["easting_m"] >= 40000]
        blocks.append(
            {
                "region_id": region["id"],
                "development_ids": development,
                "geographic_holdout_ids": held,
                "excluded_buffer_count": len(candidates) - len(development) - len(held),
                "minimum_center_separation_m": 80000,
                "context_overlap_between_folds": False,
                "status": "Prospective review partition only; no relevance labels or tolerance fitting used these folds",
            }
        )
    client = TestClient(app)
    checks = []
    for objective in ["vacuum", "base_suitability", "mineral_similarity"]:
        response = client.post(
            "/v1/rank",
            json={"target_id": "jezero", "objective": objective, "experiment": "v4"},
        )
        checks.append(
            {
                "objective": objective,
                "http": response.status_code,
                "state": response.json()["state"],
            }
        )
    for payload in [
        {"weights": [-1, 1, 1, 1]},
        {"weights": [0, 0, 0, 0]},
        {"support_m": 100},
        {"region": "not-a-catalogue-region"},
    ]:
        response = client.post("/v1/rank", json={"target_id": "jezero", **payload})
        checks.append({"input": payload, "http": response.status_code})
    durations = []
    # Warm requests include ASGI routing and full JSON serialization, excluding network.
    client.post("/v1/rank", json={"target_id": "jezero", "experiment": "v4"})
    for _ in range(100):
        start = time.perf_counter()
        response = client.post(
            "/v1/rank", json={"target_id": "jezero", "experiment": "v4"}
        )
        response.raise_for_status()
        durations.append(time.perf_counter() - start)
    pair = data["suites"]["terrain_diversity_sampling"]["jezero"]
    suite_times = []
    for _ in range(100):
        start = time.perf_counter()
        response = client.post(
            "/v1/suites", json={"rank_run_hash": pair["rank_run_hash"]}
        )
        response.raise_for_status()
        suite_times.append(time.perf_counter() - start)
    output = {
        "record_hash": data["record_hash"],
        "controls": controls,
        "known_controls": [
            {
                "region": r["name"],
                "footprint": r["bounds"],
                "role": "known_analogue_region_control",
                "expectation": "Known regional analogue use prevents a new-region discovery claim; no guaranteed terrain relevance to every target",
            }
            for r in data["regions"]
        ],
        "negative_api_controls": checks,
        "spatial_blocks": blocks,
        "independent_relevance_judgments": 0,
        "statistical_inference": "No bootstrap confidence interval: zero independent relevance labels, reused targets and few geographic units",
        "latency": {
            "machine": platform.platform(),
            "processor": platform.processor(),
            "python": platform.python_version(),
            "candidate_count": len(data["candidates"]),
            "requests_per_route": 100,
            "ranking_p95_seconds": sorted(durations)[94],
            "ranking_median_seconds": statistics.median(durations),
            "suite_p95_seconds": sorted(suite_times)[94],
            "boundary": "TestClient warm ASGI routing plus JSON serialization; fixed ranks and suites precomputed. Network, cold startup, archive acquisition and arbitrary-weight recomputation excluded.",
        },
        "baseline_bundle_hash": bundle()["protocol_hash"],
    }
    (ROOT / "artifacts/reports/discovery_evaluation.json").write_text(
        json.dumps(output, indent=2), encoding="utf-8"
    )
    print(json.dumps(output["latency"], indent=2))


if __name__ == "__main__":
    evaluate()
