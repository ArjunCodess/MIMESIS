"""Measured 4 km terrain representation and constrained two-site coverage.

This objective measures descriptor representation, allowing subwindow reuse. It
does not measure replicated area, access, or field-campaign performance.
"""

from itertools import combinations
import numpy as np
from .ranking import canonical_hash

REQUIREMENTS = ("low_slope_floor", "rugged_margin", "relief_transition", "unclassified")


def subwindows(context: np.ndarray, spacing: int):
    n = 20000 // spacing
    start = (len(context) - n) // 2
    local = context[start : start + n, start : start + n]
    size = 4000 // spacing
    result = []
    for row in range(5):
        for col in range(5):
            block = local[row * size : (row + 1) * size, col * size : (col + 1) * size]
            if np.isfinite(block).mean() < 0.95:
                result.append(
                    {"row": row, "column": col, "class": "unclassified", "values": None}
                )
                continue
            dy, dx = np.gradient(block, spacing)
            slope = np.degrees(np.arctan(np.hypot(dx, dy)))
            good = np.isfinite(slope)
            if not good.any():
                result.append(
                    {"row": row, "column": col, "class": "unclassified", "values": None}
                )
                continue
            median = float(np.median(slope[good]))
            relief = float(np.nanpercentile(block, 95) - np.nanpercentile(block, 5))
            yy, xx = np.indices(block.shape)
            mask = np.isfinite(block)
            design = np.column_stack([xx[mask], yy[mask], np.ones(mask.sum())])
            residual = (
                block[mask]
                - design @ np.linalg.lstsq(design, block[mask], rcond=None)[0]
            )
            category = (
                "low_slope_floor"
                if median <= 1 and relief <= 100
                else "rugged_margin"
                if median >= 3 or relief >= 200
                else "relief_transition"
            )
            result.append(
                {
                    "row": row,
                    "column": col,
                    "class": category,
                    "values": [
                        median,
                        float(np.percentile(slope[good], 90)),
                        relief,
                        float(np.sqrt(np.mean(residual**2))),
                    ],
                }
            )
    return result


def requirement_coverage(candidate_tiers: dict, target_tiers: dict, contract: dict):
    values = []
    nominal = target_tiers["500"]
    # Target classes remain fixed across scenarios; missing members contribute zero.
    for tier in ("500", "1000", "eroded"):
        target = target_tiers[tier]
        candidate = [
            s["values"] for s in candidate_tiers[tier] if s["values"] is not None
        ]
        matches = np.zeros(25)
        if candidate:
            for index, item in enumerate(target):
                if item["values"] is not None:
                    delta = np.minimum(
                        1,
                        np.abs(np.asarray(candidate) - item["values"])
                        / contract["subwindow_scales"],
                    )
                    distances = np.mean(delta**2, axis=1)
                    matches[index] = max(
                        0,
                        1 - float(distances.min()) / contract["requirement_tolerance"],
                    )
        values.append(
            [
                float(
                    np.mean(
                        [
                            matches[i]
                            for i, s in enumerate(nominal)
                            if s["class"] == requirement
                        ]
                    )
                )
                if any(s["class"] == requirement for s in nominal)
                and requirement != "unclassified"
                else 0.0
                for requirement in REQUIREMENTS
            ]
        )
    return np.min(values, axis=0).tolist()


def separated(a: dict, b: dict, minimum_m: float):
    if a["region_id"] != b["region_id"]:
        return True
    return (
        abs(a["easting_m"] - b["easting_m"]) >= minimum_m
        or abs(a["northing_m"] - b["northing_m"]) >= minimum_m
    )


def select_suite(
    ranking: dict,
    candidates: list[dict],
    coverage: dict,
    contract: dict,
    allowed_regions=None,
):
    lookup = {c["id"]: c for c in candidates}
    eligible = [
        r["id"]
        for r in ranking["candidates"]
        if r["passes_provisional_threshold"]
        and r["id"] in coverage
        and (allowed_regions is None or lookup[r["id"]]["region_id"] in allowed_regions)
    ]
    weights = np.asarray(contract["requirement_weights"])
    budget = contract.get("scenario_budget")
    costs = contract.get("scenario_costs", {})
    if budget is not None:
        eligible = [cid for cid in eligible if cid in costs and costs[cid] <= budget]

    def score(ids):
        value = (
            np.max([coverage[cid] for cid in ids], axis=0)
            if ids
            else np.zeros(len(REQUIREMENTS))
        )
        return {
            "candidate_ids": list(ids),
            "coverage": value.tolist(),
            "objective": float(value @ weights),
        }

    pool = eligible[:50]
    for index in range(len(REQUIREMENTS)):
        if eligible:
            best = min(eligible, key=lambda cid: (-coverage[cid][index], cid))
            if best not in pool:
                pool.append(best)
    pairs = [
        (a, b)
        for a, b in combinations(pool, 2)
        if separated(lookup[a], lookup[b], contract["minimum_context_separation_m"])
        and (budget is None or costs[a] + costs[b] <= budget)
    ]
    selected = min(
        (score(pair) for pair in pairs),
        key=lambda item: (-item["objective"], item["candidate_ids"]),
        default=score(eligible[:1]),
    )
    top_two = next(
        (
            (a, b)
            for i, a in enumerate(eligible)
            for b in eligible[i + 1 :]
            if separated(lookup[a], lookup[b], contract["minimum_context_separation_m"])
            and (budget is None or costs[a] + costs[b] <= budget)
        ),
        tuple(eligible[:1]),
    )
    rng = np.random.default_rng(contract["seed"])
    random_scores = []
    # The same evaluated pool and separation constraints apply to the random baseline.
    if pairs:
        for index in rng.choice(len(pairs), size=min(100, len(pairs)), replace=False):
            random_scores.append(score(pairs[int(index)])["objective"])
    result = {
        "state": "descriptor_coverage_only" if pairs else "no_feasible_pair",
        "rank_run_hash": ranking.get("run_hash"),
        "selected": selected,
        "single": score(eligible[:1]),
        "top_two": score(top_two),
        "random_pair_mean": float(np.mean(random_scores)) if random_scores else None,
        "random_pair_count": len(random_scores),
        "eligible_count": len(eligible),
        "evaluated_pool": pool,
        "evaluated_pair_count": len(pairs),
        "requirements": list(REQUIREMENTS),
        "uncovered_requirements": [
            r
            for r, v in zip(REQUIREMENTS, selected["coverage"])
            if v < contract["minimum_reportable_coverage"]
        ],
        "contract": contract,
        "limitation": "Best evaluated pair from top 50 plus requirement representatives; descriptor coverage permits subwindow reuse and is not independent evidence of field usefulness. Missing/empty target classes have zero coverage. No access or permission is inferred.",
    }
    result["run_hash"] = canonical_hash(result)
    return result
