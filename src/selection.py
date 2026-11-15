"""Frozen context-separated nominations and category/coverage-matched alternatives."""

import numpy as np


def terrain_category(candidate: dict, rule: dict):
    f = candidate["features"]["500"]
    # Predeclared physical bins, fixed before the corrected shortlist is viewed.
    return (
        int(
            np.searchsorted(
                rule["slope_category_edges_deg"], f["slope_median_deg"], side="right"
            )
        ),
        int(
            np.searchsorted(
                rule["relief_category_edges_m"], f["relief_m"], side="right"
            )
        ),
    )


def freeze_shortlist(rows: list[dict], candidates: list[dict], rule: dict, seed: int):
    lookup = {c["id"]: c for c in candidates}
    by_rank = {r["id"]: r for r in rows}
    selected = []
    roles = {}
    matches = {}

    def separated(candidate):
        return all(
            candidate.get("region_id") != lookup[key].get("region_id")
            or abs(candidate["easting_m"] - lookup[key]["easting_m"])
            >= rule["minimum_context_separation_m"]
            or abs(candidate["northing_m"] - lookup[key]["northing_m"])
            >= rule["minimum_context_separation_m"]
            for key in selected
        )

    for row in rows:
        candidate = lookup[row["id"]]
        if separated(candidate):
            selected.append(candidate["id"])
            roles[candidate["id"]] = "nomination"
        if len(selected) == 3:
            break
    nominations = selected.copy()
    rng = np.random.default_rng(seed)
    tie_order = {
        c["id"]: float(value)
        for c, value in zip(candidates, rng.random(len(candidates)))
    }
    for nomination_id in nominations:
        nomination = lookup[nomination_id]
        nominal = by_rank[nomination_id]
        pool = [
            row
            for row in rows
            if row["id"] not in selected
            and row["rank"] > nominal["rank"]
            and terrain_category(lookup[row["id"]], rule)
            == terrain_category(nomination, rule)
            and abs(
                lookup[row["id"]]["features"]["500"]["context_valid_fraction"]
                - nomination["features"]["500"]["context_valid_fraction"]
            )
            <= rule["maximum_context_coverage_difference"]
            and abs(
                lookup[row["id"]]["features"]["500"]["valid_fraction"]
                - nomination["features"]["500"]["valid_fraction"]
            )
            <= rule["maximum_local_coverage_difference"]
            and separated(lookup[row["id"]])
        ]
        if pool:
            chosen = min(
                pool,
                key=lambda row: (
                    abs(row["nominal_loss"] - nominal["nominal_loss"]),
                    tie_order[row["id"]],
                    row["id"],
                ),
            )["id"]
            selected.append(chosen)
            roles[chosen] = "matched_alternative"
            matches[chosen] = nomination_id
    unfilled = [
        {
            "role": "nomination",
            "reason": "No additional ranked candidate has a non-overlapping 80 km context",
        }
        for _ in range(3 - len(nominations))
    ]
    for nomination_id in nominations:
        if nomination_id not in matches.values():
            unfilled.append(
                {
                    "role": "matched_alternative",
                    "matched_to": nomination_id,
                    "reason": "No lower-ranked candidate matches both terrain categories and coverage tolerances while preserving non-overlapping 80 km contexts",
                }
            )
    unfilled.extend(
        {
            "role": "matched_alternative",
            "matched_to": None,
            "reason": "The corresponding third nomination could not be filled under context separation",
        }
        for _ in range(3 - len(nominations))
    )
    return selected, roles, matches, unfilled
