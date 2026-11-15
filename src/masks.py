"""Conservative modern land-modification masks and context-scale declustering."""

import numpy as np
from scipy.ndimage import distance_transform_edt
from .suites import separated


def natural_land_mask(
    classes: np.ndarray, roads: np.ndarray, spacing_m: int, buffer_m: int
):
    """Classes: 0 mapped unflagged, 1 mapped modification, 2 unknown coverage.

    Unflagged is not proof of natural land. Source classification errors, OSM
    omissions and acquisition dates remain limitations of the experiment.
    """
    if classes.shape != roads.shape or roads.dtype != bool:
        raise ValueError("Classification and boolean road masks must share a grid")
    human = (classes == 1) | roads
    buffered = (
        distance_transform_edt(~human, sampling=spacing_m) <= buffer_m
        if human.any()
        else human
    )
    return (classes == 0) & ~buffered, {
        "mapped_modified_fraction": float(human.mean()),
        "unknown_fraction": float((classes == 2).mean()),
        "buffered_modified_fraction": float(buffered.mean()),
        "buffer_m": buffer_m,
        "interpretation": "Sensitivity to mapped modern modification; not verified absence of human disturbance or causal evidence about historical DEM construction",
    }


def decluster(rows: list[dict], candidates: list[dict], minimum_m=80000):
    lookup = {c["id"]: c for c in candidates}
    selected, suppressed = [], []
    for row in rows:
        conflict = next(
            (
                r["id"]
                for r in selected
                if not separated(lookup[row["id"]], lookup[r["id"]], minimum_m)
            ),
            None,
        )
        if conflict is None:
            selected.append({**row, "declustered_rank": len(selected) + 1})
        else:
            suppressed.append(
                {
                    "candidate_id": row["id"],
                    "suppressed_by": conflict,
                    "reason": "Overlapping 80km context in the same local coordinate region",
                }
            )
    return {
        "selected": selected,
        "suppressed": suppressed,
        "minimum_context_separation_m": minimum_m,
        "interpretation": "Greedy score-ordered non-overlapping contexts; separation does not establish statistical independence or a global retrieval optimum",
    }
