"""One scoring implementation shared by research, API and static exports."""

import hashlib
import json
import numpy as np
from .terrain import SLOPE_CENTERS


def canonical_hash(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def group_losses(candidate: dict, target: dict, tolerances: dict) -> list[float]:
    if not candidate or not target:
        return [1.0] * 4

    def loss(key, scale):
        if candidate.get(key) is None or target.get(key) is None:
            return 1.0
        return float(min(1, abs(candidate[key] - target[key]) / scale) ** 2)

    # W1 for shared discrete bin centers equals integral of absolute CDF difference.
    cdf_delta = np.cumsum(
        np.array(candidate["slope_histogram"]) - target["slope_histogram"]
    )
    w1 = float(np.sum(np.abs(cdf_delta[:-1]) * np.diff(SLOPE_CENTERS)))
    return [
        min(1, w1 / tolerances["slope_w1_degrees"]) ** 2,
        (
            loss("relief_m", tolerances["relief_m"])
            + loss("tpi_std_m", tolerances["tpi_m"])
        )
        / 2,
        (
            loss("residual_rms_m", tolerances["residual_m"])
            + loss("anisotropy", tolerances["anisotropy"])
        )
        / 2,
        (
            loss("context_relief_m", tolerances["context_relief_m"])
            + loss("context_std_m", tolerances["context_relief_m"] / 4)
        )
        / 2,
    ]


def rank(
    candidates: list[dict],
    target: dict,
    protocol: dict,
    support: int = 500,
    weights=None,
):
    weights = np.array(protocol["weights"] if weights is None else weights, dtype=float)
    weights /= weights.sum()
    tier = str(support)
    other = "1000" if support == 500 else "500"
    if not target["features"].get(tier):
        return {
            "state": "insufficient_evidence",
            "reason": "Required target terrain is unavailable",
            "candidates": [],
        }
    eligible = [
        c
        for c in candidates
        if c["features"].get(tier)
        and c["features"].get(other)
        and c["features"].get("eroded")
    ]
    if not eligible:
        return {
            "state": "no_candidate_passes",
            "reason": "No window meets required coverage in every sensitivity tier",
            "candidates": [],
        }
    tolerances = protocol["tolerances"]
    groups = np.array(
        [
            group_losses(c["features"][tier], target["features"][tier], tolerances)
            for c in eligible
        ]
    )
    other_groups = np.array(
        [
            group_losses(c["features"][other], target["features"][other], tolerances)
            for c in eligible
        ]
    )
    eroded_groups = np.array(
        [
            group_losses(
                c["features"]["eroded"], target["features"]["eroded"], tolerances
            )
            for c in eligible
        ]
    )
    rng = np.random.default_rng(protocol["scenario_seed"])
    variations = (
        rng.uniform(0.8, 1.2, (protocol["random_weight_scenarios"], 4)) * weights
    )
    variations /= variations.sum(axis=1, keepdims=True)
    nominal = groups @ weights
    scenarios = np.column_stack(
        [
            nominal,
            groups @ variations.T,
            other_groups @ weights,
            eroded_groups @ weights,
        ]
    )
    robust = scenarios.max(axis=1)
    order = sorted(
        range(len(eligible)), key=lambda i: (robust[i], nominal[i], eligible[i]["id"])
    )
    ranks = np.empty_like(scenarios, dtype=int)
    for s in range(scenarios.shape[1]):
        ids = sorted(
            range(len(eligible)),
            key=lambda i: (scenarios[i, s], nominal[i], eligible[i]["id"]),
        )
        ranks[ids, s] = np.arange(1, len(ids) + 1)
    result = []
    for position, i in enumerate(order):
        result.append(
            {
                "id": eligible[i]["id"],
                "rank": position + 1,
                "nominal_loss": float(nominal[i]),
                "robust_loss": float(robust[i]),
                "group_losses": groups[i].tolist(),
                "contributions": (groups[i] * weights).tolist(),
                "scenario_rank_range": [int(ranks[i].min()), int(ranks[i].max())],
                "top10_inclusion_fraction": float(np.mean(ranks[i] <= 10)),
                "passes_provisional_threshold": bool(
                    robust[i] <= protocol["provisional_maximum_loss"]
                ),
                "claim_level": "screened_candidate",
            }
        )
    scientific_candidates = [
        {
            key: c[key]
            for key in ("id", "features", "source_ids", "latitude", "longitude")
            if key in c
        }
        for c in eligible
    ]
    scientific_target = {
        key: target[key]
        for key in ("id", "features", "source", "latitude", "longitude", "projection")
        if key in target
    }
    run_input = {
        "protocol": protocol,
        "target": scientific_target,
        "candidates": scientific_candidates,
        "support": support,
        "weights": weights.tolist(),
    }
    passes = any(row["passes_provisional_threshold"] for row in result)
    return {
        "state": "insufficient_evidence" if passes else "no_candidate_passes",
        "reason": "Measured screening only; corroboration, novelty and independent review are unresolved"
        if passes
        else "No measured candidate passes the provisional discrepancy cutoff; nearest neighbours are retained for inspection",
        "run_hash": canonical_hash(run_input),
        "support_m": support,
        "weights": weights.tolist(),
        "scenario_count": scenarios.shape[1],
        "excluded_count": len(candidates) - len(eligible),
        "candidates": result,
    }
