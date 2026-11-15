"""Independent-data diagnostics and honest contact/statistical reference gates."""

from itertools import product
import math
import numpy as np
from scipy.ndimage import binary_erosion
from scipy.stats import wasserstein_distance_nd
from scipy.spatial import cKDTree


def fine_morphometry(grid: np.ndarray, spacing_m: float):
    valid = binary_erosion(np.isfinite(grid), iterations=2, border_value=0)
    if np.mean(np.isfinite(grid)) < 0.95 or not valid.any():
        return {
            "state": "insufficient_evidence",
            "valid_fraction": float(np.isfinite(grid).mean()),
        }
    dy, dx = np.gradient(grid, spacing_m)
    slope = np.degrees(np.arctan(np.hypot(dx, dy)))
    curvature = np.gradient(dx, spacing_m, axis=1) + np.gradient(dy, spacing_m, axis=0)
    # Fixed physical scaling and bins; no scale is fitted to the pair under test.
    histogram, _, _ = np.histogram2d(
        np.minimum(slope[valid], 20),
        np.clip(curvature[valid], -0.002, 0.002),
        bins=[np.linspace(0, 20, 17), np.linspace(-0.002, 0.002, 17)],
    )
    histogram /= histogram.sum()
    values = grid[np.isfinite(grid)]
    extent = float(np.max(values) - np.min(values))
    return {
        "state": "measured_fine_morphometry",
        "valid_fraction": float(np.isfinite(grid).mean()),
        "joint_histogram": histogram.tolist(),
        "hypsometric_integral": float((values.mean() - values.min()) / extent)
        if extent > 0
        else 0.0,
        "median_slope_deg": float(np.median(slope[valid])),
        "relief_m": float(np.percentile(values, 95) - np.percentile(values, 5)),
        "spacing_m": spacing_m,
        "curvature_units": "m-1, planar Laplacian of height",
        "hi_limitation": "Uses observed min/max; sensitive to outliers. A constant surface has HI0 by declared convention.",
    }


def compare_fine(a: dict, b: dict):
    if (
        a["state"] != "measured_fine_morphometry"
        or b["state"] != "measured_fine_morphometry"
    ):
        return {
            "state": "insufficient_paired_coverage",
            "joint_wasserstein": None,
            "hypsometric_difference": None,
        }
    slope = (np.arange(16) + 0.5) * 20 / 16 / 5
    curvature = ((np.arange(16) + 0.5) * 0.004 / 16 - 0.002) / 0.001
    sx, cy = np.meshgrid(slope, curvature, indexing="ij")
    points = np.column_stack([sx.ravel(), cy.ravel()])
    left, right = (
        np.asarray(a["joint_histogram"]).ravel(),
        np.asarray(b["joint_histogram"]).ravel(),
    )
    return {
        "state": "descriptor_comparison_only",
        "joint_wasserstein": float(
            wasserstein_distance_nd(
                points[left > 0], points[right > 0], left[left > 0], right[right > 0]
            )
        ),
        "hypsometric_difference": abs(
            a["hypsometric_integral"] - b["hypsometric_integral"]
        ),
        "normalization": "slope/5 degrees and curvature/.001m-1; fixed engineering scales",
        "limitation": "Cross-sensor descriptor distance does not establish geological equivalence or mapping rehearsal usefulness",
    }


def paired_sign_test(differences: list[float]):
    values = [v for v in differences if v != 0]
    if not values:
        return {
            "nonzero_target_pairs": 0,
            "wins": 0,
            "one_sided_p": None,
            "state": "no_complete_nonzero_pairs",
        }
    wins, n = sum(v > 0 for v in values), len(values)
    p = sum(math.comb(n, k) for k in range(wins, n + 1)) / 2**n
    return {
        "nonzero_target_pairs": n,
        "wins": wins,
        "one_sided_p": p,
        "state": "conditional_descriptive_test",
        "assumption": "One independent target-level difference per complete frozen pair; this calculation does not establish target independence or correct missing-pair selection",
    }


def paired_randomization(differences: list[float]):
    if not differences:
        return {"pair_count": 0, "one_sided_p": None}
    if len(differences) > 20:
        raise ValueError("Exact enumeration is limited to20 target units")
    values = np.asarray(differences)
    observed = float(values.mean())
    exceed = sum(
        float(np.mean(values * signs)) >= observed - 1e-12
        for signs in product([-1, 1], repeat=len(values))
    )
    return {
        "pair_count": len(values),
        "mean_difference": observed,
        "one_sided_p": exceed / 2 ** len(values),
        "assumption": "Exchangeable signs across independent target units; no claim that these assumptions have been externally validated",
    }


def boundary_f1(
    predicted: np.ndarray,
    reference: np.ndarray,
    tolerance_m: float,
    reference_accuracy_m: float,
    map_scale_denominator: float | None = None,
):
    minimum = max(reference_accuracy_m, (map_scale_denominator or 0) * 0.0005)
    if tolerance_m < minimum:
        return {
            "state": "reference_too_coarse",
            "f1": None,
            "minimum_tolerance_m": minimum,
            "reason": "Requested tolerance is below declared positional accuracy or a .5mm map-scale floor; a global map cannot establish fine contact accuracy",
        }
    if len(predicted) < 2 or len(reference) < 2:
        return {"state": "insufficient_reference", "f1": None}

    def densify(line):
        points = []
        for a, b in zip(line[:-1], line[1:]):
            count = max(1, int(np.ceil(np.linalg.norm(b - a) / (tolerance_m / 4))))
            points.extend(
                a + (b - a) * fraction for fraction in np.arange(count) / count
            )
        return np.asarray(points + [line[-1]])

    left, right = densify(predicted), densify(reference)
    precision = float(np.mean(cKDTree(right).query(left)[0] <= tolerance_m))
    recall = float(np.mean(cKDTree(left).query(right)[0] <= tolerance_m))
    return {
        "state": "diagnostic_against_supplied_reference",
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall)
        if precision + recall
        else 0,
        "tolerance_m": tolerance_m,
        "sampling_step_max_m": tolerance_m / 4,
        "limitation": "Densified-line nearest-sample approximation; reference validity, registration, blinding and operational usefulness require separate verification",
    }
