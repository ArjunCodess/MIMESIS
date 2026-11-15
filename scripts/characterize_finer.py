"""Acquire real stereo DTMs and test a separate local terrain comparison.

Stereo geometry adds observations, but CTX is registered to MOLA and Kaguya
products can be registered to LOLA. Shared vertical/geometric ancestry remains
explicit; these are not fully independent absolute elevation measurements.
"""

import hashlib
import json
from pathlib import Path
import requests
import numpy as np
import rasterio
from pyproj import CRS, Transformer
from scipy.ndimage import map_coordinates
from src.terrain import open_nasadem_mosaic, project_window, smooth_grid

ROOT = Path(__file__).resolve().parents[1]


def summarize(grid, spacing):
    good = np.isfinite(grid)
    dy, dx = np.gradient(grid, spacing)
    slope = np.degrees(np.arctan(np.hypot(dx, dy)))
    return {
        "valid_fraction": float(good.mean()),
        "relief_m": float(np.nanpercentile(grid, 95) - np.nanpercentile(grid, 5))
        if good.any()
        else None,
        "slope_median_deg": float(np.nanmedian(slope))
        if np.isfinite(slope).any()
        else None,
        "slope_p90_deg": float(np.nanpercentile(slope, 90))
        if np.isfinite(slope).any()
        else None,
    }


def sample_stereo(path, lat, lon, radius, extent=22000, spacing=50):
    with rasterio.open(path) as source:
        expected = CRS.from_wkt(source.crs.to_wkt())
        if abs(expected.ellipsoid.semi_major_metre - radius) > 1000:
            raise ValueError("Planetary body radius does not match the stereo asset")
        local = CRS.from_proj4(
            f"+proj=aeqd +lat_0={lat} +lon_0={lon} +R={radius} +units=m"
        )
        transform = Transformer.from_crs(local, expected, always_xy=True)
        axis = np.arange(-extent / 2 + spacing / 2, extent / 2, spacing)
        x, y = np.meshgrid(axis, -axis)
        sx, sy = transform.transform(x, y)
        inverse = ~source.transform
        cols, rows = inverse * (sx, sy)
        data = source.read(1).astype(float)
        valid = (data != source.nodata) & np.isfinite(data)
        weights = map_coordinates(
            valid.astype(float),
            [rows - 0.5, cols - 0.5],
            order=1,
            mode="constant",
            cval=0,
        )
        values = map_coordinates(
            np.where(valid, data, 0),
            [rows - 0.5, cols - 0.5],
            order=1,
            mode="constant",
            cval=0,
        )
        grid = np.where(weights > 0.999, values, np.nan)
        return grid, {
            "crs": source.crs.to_wkt(),
            "source_grid_spacing_m": list(source.res),
            "nodata": source.nodata,
            "body_radius_m": radius,
        }


def characterize():
    b = json.loads((ROOT / "apps/web/public/research/bundle.json").read_text())
    records = []
    for tid, radius in [
        ("jezero", 3396190),
        ("syrtis", 3396190),
        ("shackleton", 1737400),
    ]:
        items = json.loads(
            (ROOT / f"data/metadata/{tid}-stereo-stac.json").read_text()
        )["features"]
        item = items[0]
        url = item["assets"]["dtm"]["href"]
        folder = ROOT / f"data/raw/{'moon' if tid == 'shackleton' else 'mars'}/stereo"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{item['id']}.tif"
        if not path.exists():
            response = requests.get(url, timeout=120)
            response.raise_for_status()
            path.write_bytes(response.content)
        target = next(t for t in b["targets"] if t["id"] == tid)
        grid, metadata = sample_stereo(
            path, target["latitude"], target["longitude"], radius
        )
        smoothed = smooth_grid(grid, 50, 100)[20:-20, 20:-20][::2, ::2]
        planetary = summarize(smoothed, 100)
        record = {
            "target_id": tid,
            "source_id": item["id"],
            "source_url": url,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "license": item["properties"].get("license"),
            "source_description": item["properties"]["description"],
            "metadata": metadata,
            "analysis_spacing_m": 100,
            "window_m": 20000,
            "effective_support": "100m analysis spacing; stereo matching precision and effective resolution not independently calibrated",
            "planetary": planetary,
            "state": "available_local_comparison"
            if planetary["valid_fraction"] >= 0.95
            else "insufficient_stereo_coverage",
            "lineage": "CTX stereo is absolutely aligned to MOLA; Kaguya product alignment to LOLA must be consulted in the retained provenance. Separate local surface observations, shared reference control; not fully independent absolute heights.",
        }
        if tid == "jezero":
            expanded = json.loads(
                (ROOT / "apps/web/public/research/discovery.json").read_text()
            )
            nominated = {
                d["candidate_id"]
                for d in expanded["investigations"][tid]["shortlist"]
                if d["role"] == "nomination"
            }
            record["earth_comparisons"] = []
            for candidate in expanded["candidates"]:
                if candidate["id"] not in nominated:
                    continue
                region = next(
                    r for r in expanded["regions"] if r["id"] == candidate["region_id"]
                )
                raster = open_nasadem_mosaic(
                    ROOT / "data/raw/earth/nasadem",
                    region["tiles"],
                    ROOT / f"data/processed/finer-{region['id']}-mosaic.hgt",
                )
                earth, _ = project_window(
                    raster, candidate["latitude"], candidate["longitude"], 22000, 50
                )
                earth = smooth_grid(earth, 50, 100)[20:-20, 20:-20][::2, ::2]
                measured = summarize(earth, 100)
                record["earth_comparisons"].append(
                    {
                        "candidate_id": candidate["id"],
                        "earth": measured,
                        "paired_state": "measured_local_comparison"
                        if measured["valid_fraction"] >= 0.95
                        and planetary["valid_fraction"] >= 0.95
                        else "insufficient_paired_coverage",
                    }
                )
                np.savez_compressed(
                    ROOT / f"data/processed/{candidate['id']}-finer-comparison.npz",
                    earth=earth,
                    planetary=smoothed,
                    spacing_m=100,
                )
        records.append(record)
        print(tid, record["state"], planetary, flush=True)
    output = ROOT / "artifacts/reports/finer_support.json"
    output.write_text(json.dumps(records, indent=2), encoding="utf-8")
    (ROOT / "apps/web/public/research/finer_support.json").write_bytes(
        output.read_bytes()
    )


if __name__ == "__main__":
    characterize()
