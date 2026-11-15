"""Source-linked MOLA point support and declared Earth sampling diagnostics.

Neither count rasters nor CTX-minus-MOLA residuals are shot elevation inputs.
The sampler transfers metric positions, not planetary heights or uncertainty.
"""

from dataclasses import dataclass
import csv
from pathlib import Path

import numpy as np
from pyproj import CRS, Transformer
from scipy.interpolate import LinearNDInterpolator, RegularGridInterpolator
from scipy.spatial import cKDTree
from scipy.ndimage import binary_erosion


@dataclass(frozen=True)
class Shots:
    longitude: np.ndarray
    latitude: np.ndarray
    radius_m: np.ndarray
    elevation_m: np.ndarray | None
    orbit: np.ndarray | None
    time_s: np.ndarray | None
    attitude: np.ndarray | None
    source_url: str
    source_kind: str
    duplicate_rows_removed: int


def read_shots(path: Path, *, source_url: str, source_kind: str,
               units: str, body: str, label: Path | None = None) -> Shots:
    """Validate the external format once; retain missing quality as missing.

    ODE field mapping follows the accompanying PDS label. Control-radius CSVs
    require an explicit caller declaration because their header omits units.
    """
    if body != "Mars" or units != "m" or not source_url.startswith("https://"):
        raise ValueError("Declare Mars, metre units and a retrievable HTTPS source")
    if source_kind not in {"ode_pedr", "ctx_control_radius"}:
        raise ValueError("Only shot tables are accepted; binned counts/residuals are not shots")
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream, skipinitialspace=True)
        rows = [{k.strip(): v.strip() for k, v in row.items()} for row in reader]
    expected = ({"LONG_EAST", "LAT_NORTH", "PLANET_RAD", "TOPOGRAPHY", "ORBIT",
                 "EMPHEMERIS_TIME", "UTC", "C", "A"} if source_kind == "ode_pedr"
                else {"latitude", "longitude", "radius"})
    if not rows or not expected.issubset(rows[0]):
        raise ValueError(f"Missing required shot fields: {sorted(expected)}")
    if source_kind == "ode_pedr":
        if label is None:
            raise ValueError("ODE input requires its PDS label")
        text = label.read_text()
        for token in ['TARGET_NAME                = "MARS"', 'IAU2000',
                      'UNIT                = "METER"', 'SHOT_PLANETARY_RADIUS']:
            if token not in text:
                raise ValueError(f"Unsupported ODE label: missing {token}")
    lon_key, lat_key, radius_key = (("LONG_EAST", "LAT_NORTH", "PLANET_RAD")
                                  if source_kind == "ode_pedr" else
                                  ("longitude", "latitude", "radius"))
    lon, lat, radius = (np.array([float(r[k]) for r in rows])
                        for k in (lon_key, lat_key, radius_key))
    if (not np.isfinite(np.column_stack([lon, lat, radius])).all()
            or np.any((lat < -90) | (lat > 90))
            or np.any((lon < -180) | (lon > 360))
            or np.any((radius < 3_300_000) | (radius > 3_500_000))):
        raise ValueError("Invalid Mars shot coordinates/radii or incorrect radius units")
    elevation = orbit = time = attitude = None
    if source_kind == "ode_pedr":
        elevation = np.array([float(r['TOPOGRAPHY']) for r in rows])
        orbit = np.array([int(r['ORBIT']) for r in rows])
        time = np.array([float(r['EMPHEMERIS_TIME']) for r in rows])
        attitude = np.array([int(r['A']) for r in rows])
        if not np.isfinite(elevation).all() or not np.isfinite(time).all():
            raise ValueError("Nonfinite shot time or topography")
        identities = np.column_stack([orbit, time])
    else:
        identities = np.column_stack([lon % 360, lat, radius])
    _, indices, inverse = np.unique(identities, axis=0, return_index=True, return_inverse=True)
    # A repeated time identity with conflicting positions is an error, not a replicate.
    if not np.allclose(np.column_stack([lon, lat, radius]),
                       np.column_stack([lon, lat, radius])[indices][inverse], rtol=0, atol=1e-6):
        raise ValueError("Conflicting duplicate orbit/time identity")
    indices = np.sort(indices)
    return Shots((lon[indices] + 180) % 360 - 180, lat[indices], radius[indices],
                 None if elevation is None else elevation[indices],
                 None if orbit is None else orbit[indices],
                 None if time is None else time[indices],
                 None if attitude is None else attitude[indices], source_url,
                 source_kind, len(rows) - len(indices))


def project_shots(shots: Shots, longitude: float, latitude: float,
                  radius_m: float = 3_396_000) -> np.ndarray:
    if not 3_300_000 <= radius_m <= 3_500_000:
        raise ValueError("Use a Mars metric projection radius in metres")
    geographic = CRS.from_proj4(f"+proj=longlat +R={radius_m}")
    local = CRS.from_proj4(f"+proj=aeqd +lat_0={latitude} +lon_0={longitude} +R={radius_m} +units=m")
    x, y = Transformer.from_crs(geographic, local, always_xy=True).transform(
        shots.longitude, shots.latitude)
    return np.column_stack([x, y])


def support_geometry(shots: Shots, xy: np.ndarray, *, half_width_m: float,
                     max_time_gap_s: float = 0.3) -> dict:
    keep = np.max(np.abs(xy), axis=1) <= half_width_m
    if shots.attitude is not None:
        keep &= shots.attitude == 0
    positions = xy[keep]
    if not len(positions):
        return {"state": "no_points_in_context", "retained_points": 0}
    result = {"state": "measured_point_support", "retained_points": len(positions),
              "attitude_rejected": 0 if shots.attitude is None else int(np.sum(shots.attitude != 0)),
              "shot_quality_flag": None, "duplicates_removed": shots.duplicate_rows_removed,
              "orbit_count": None, "along_track_spacing_m": None,
              "time_gaps_over_threshold": None}
    if shots.orbit is not None:
        orbit, time = shots.orbit[keep], shots.time_s[keep]
        order = np.lexsort((time, orbit))
        dt = np.diff(time[order]); same = np.diff(orbit[order]) == 0
        consecutive = same & (dt > 0) & (dt <= max_time_gap_s)
        distances = np.linalg.norm(np.diff(positions[order], axis=0), axis=1)[consecutive]
        result.update(orbit_count=len(np.unique(orbit)),
                      time_gaps_over_threshold=int(np.sum(same & (dt > max_time_gap_s))),
                      along_track_spacing_m=None if not len(distances) else
                      {"p05": float(np.percentile(distances, 5)), "median": float(np.median(distances)),
                       "p95": float(np.percentile(distances, 95))})
    return result


def sample_earth_support(elevation: np.ndarray, spacing_m: float, xy: np.ndarray,
                         *, half_width_m: float = 40_000, output_spacing_m: float = 500,
                         maximum_nearest_shot_m: float = 1000) -> dict:
    """Copy metric x/y without rotation/scaling; bilinear point sampling then linear TIN.

    No extrapolation outside the point hull or across the declared distance cap.
    No laser-footprint response or error model is inferred from point geometry.
    """
    yaxis = ((elevation.shape[0] - 1) / 2 - np.arange(elevation.shape[0])) * spacing_m
    xaxis = (np.arange(elevation.shape[1]) - (elevation.shape[1] - 1) / 2) * spacing_m
    sampler = RegularGridInterpolator((yaxis[::-1], xaxis), elevation[::-1],
                                      bounds_error=False, fill_value=np.nan)
    selected = xy[np.max(np.abs(xy), axis=1) <= half_width_m]
    heights = sampler(selected[:, ::-1]); finite = np.isfinite(heights)
    selected, heights = selected[finite], heights[finite]
    axis = np.arange(-half_width_m + output_spacing_m / 2, half_width_m, output_spacing_m)
    x, y = np.meshgrid(axis, axis[::-1]); points = np.column_stack([x.ravel(), y.ravel()])
    baseline = sampler(points[:, ::-1]).reshape(x.shape)
    if len(heights) < 3 or np.linalg.matrix_rank(selected - selected.mean(axis=0)) < 2:
        return {"state": "insufficient_2d_sampling", "sampled_points": len(heights)}
    reconstruction = LinearNDInterpolator(selected, heights)(points)
    nearest = cKDTree(selected).query(points)[0]
    reconstruction[nearest > maximum_nearest_shot_m] = np.nan
    reconstruction = reconstruction.reshape(x.shape)
    common = binary_erosion(np.isfinite(baseline) & np.isfinite(reconstruction), iterations=2)
    if not common.any():
        return {"state": "insufficient_common_support", "sampled_points": len(heights)}
    descriptors = []
    for grid in [baseline, reconstruction]:
        dy, dx = np.gradient(grid, output_spacing_m)
        laplacian = np.gradient(dx, output_spacing_m, axis=1) + np.gradient(dy, output_spacing_m, axis=0)
        descriptors.append({"median_slope_deg": float(np.median(np.degrees(np.arctan(np.hypot(dx, dy)))[common])),
                            "median_abs_planar_laplacian_m_inverse": float(np.median(np.abs(laplacian[common]))),
                            "relief_p95_minus_p05_m": float(np.diff(np.percentile(grid[common], [5, 95]))[0])})
    return {"state": "measured_support_sensitivity", "sampled_points": len(heights),
            "baseline_valid_fraction": float(np.isfinite(baseline).mean()),
            "reconstructed_valid_fraction": float(np.isfinite(reconstruction).mean()),
            "common_derivative_valid_fraction": float(common.mean()),
            "nearest_point_distance_p50_p95_max_m": np.percentile(nearest, [50, 95, 100]).tolist(),
            "common_support_rmse_m": float(np.sqrt(np.mean((baseline[common] - reconstruction[common]) ** 2))),
            "baseline": descriptors[0], "shot_sampled": descriptors[1],
            "descriptor_difference": {k: descriptors[1][k] - descriptors[0][k] for k in descriptors[0]},
            "independent_repetitions": None,
            "limitation": "One fixed support transfer per Earth field; shots are correlated observations, not independent repetitions. Unknown shot quality is retained; no calibrated footprint, noise model, original MEGDR kernel or mapping-utility inference."}
