"""Acquire additional Earth DSM observations and report prospective fine diagnostics.

No missing matched control or fine contact reference is manufactured. Copernicus
DSM may contain auxiliary SRTM fill; CTX is MOLA-aligned. Source independence is
therefore limited even though the primary sensing observations differ.
"""

import hashlib
import json
import math
from pathlib import Path
import numpy as np
import rasterio
from rasterio.windows import from_bounds, Window
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_origin
from pyproj import CRS, Transformer
from scipy.ndimage import map_coordinates
from characterize_finer import sample_stereo
from src.terrain import smooth_grid
from src.masks import natural_land_mask
from src.validation import (
    fine_morphometry,
    compare_fine,
    paired_sign_test,
    paired_randomization,
)

ROOT = Path(__file__).resolve().parents[1]


def match_local(grid):
    smoothed = smooth_grid(grid, 50, 100)
    axis = np.arange(20.5, 420, 2)
    yy, xx = np.meshgrid(axis, axis, indexing="ij")
    return map_coordinates(smoothed, [yy, xx], order=1, mode="constant", cval=np.nan)


def acquire_earth(candidate, region, buffer_m, version="v5"):
    folder = ROOT / "data/raw/earth/copernicus"
    folder.mkdir(parents=True, exist_ok=True)
    lat, lon = candidate["latitude"], candidate["longitude"]
    local = CRS.from_proj4(
        f"+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m"
    )
    inverse = Transformer.from_crs(local, "EPSG:4326", always_xy=True)
    axis = np.arange(-10975, 11000, 50)
    x, y = np.meshgrid(axis, -axis)
    longitude, latitude = inverse.transform(x, y)
    earth = np.full(x.shape, np.nan)
    sources = []
    for south in range(math.floor(latitude.min()), math.floor(latitude.max()) + 1):
        for west in range(math.floor(longitude.min()), math.floor(longitude.max()) + 1):
            name = f"Copernicus_DSM_COG_10_{'N' if south >= 0 else 'S'}{abs(south):02d}_00_{'E' if west >= 0 else 'W'}{abs(west):03d}_00_DEM"
            url = f"https://copernicus-dem-30m.s3.amazonaws.com/{name}/{name}.tif"
            path = folder / f"{candidate['id']}-{south}-{west}-clip.tif"
            if not path.exists():
                with rasterio.Env(
                    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
                    GDAL_HTTP_TIMEOUT=90,
                ):
                    with rasterio.open(url) as source:
                        bbox = (
                            max(float(longitude.min()) - 0.001, source.bounds.left),
                            max(float(latitude.min()) - 0.001, source.bounds.bottom),
                            min(float(longitude.max()) + 0.001, source.bounds.right),
                            min(float(latitude.max()) + 0.001, source.bounds.top),
                        )
                        window = (
                            from_bounds(*bbox, transform=source.transform)
                            .round_offsets()
                            .round_lengths()
                            .intersection(Window(0, 0, source.width, source.height))
                        )
                        values = source.read(1, window=window)
                        with rasterio.open(
                            path,
                            "w",
                            driver="GTiff",
                            width=values.shape[1],
                            height=values.shape[0],
                            count=1,
                            dtype=values.dtype,
                            crs=source.crs,
                            transform=source.window_transform(window),
                            nodata=source.nodata,
                            compress="DEFLATE",
                        ) as destination:
                            destination.write(values, 1)
                            destination.update_tags(
                                source_url=url,
                                source_window=json.dumps(list(window.flatten())),
                                role="Separate DSM context; filling-mask ancestry unavailable",
                            )
            with rasterio.open(path) as source:
                values = source.read(1).astype(float)
                valid = np.isfinite(values)
                if source.nodata is not None:
                    valid &= values != source.nodata
                cols, rows = (~source.transform) * (longitude, latitude)
                good = (
                    map_coordinates(
                        valid.astype(float),
                        [rows - 0.5, cols - 0.5],
                        order=1,
                        mode="constant",
                        cval=0,
                    )
                    > 0.999
                )
                sampled = map_coordinates(
                    np.where(valid, values, 0),
                    [rows - 0.5, cols - 0.5],
                    order=1,
                    mode="constant",
                    cval=0,
                )
                earth[good] = sampled[good]
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            sources.append(
                {
                    "url": url,
                    "native_clip": path.relative_to(ROOT).as_posix(),
                    "sha256": digest,
                }
            )
    masks = np.load(
        ROOT
        / f"data/processed/{region['id']}-human-masks{'' if version == 'v5' else '-v6'}.npz"
    )
    natural, _ = natural_land_mask(masks["classes"], masks["roads"], 125, buffer_m)
    # Reproject the conservative regional invalidity, preserving body/CRS semantics.
    invalid = np.ones(earth.shape, dtype=np.uint8)
    source_crs = CRS.from_proj4(
        f"+proj=aeqd +lat_0={region['latitude']} +lon_0={region['longitude']} +datum=WGS84 +units=m"
    )
    reproject(
        (~natural).astype(np.uint8),
        invalid,
        src_transform=from_origin(-116000, 116000, 125, 125),
        src_crs=source_crs,
        dst_transform=from_origin(-11000, 11000, 50, 50),
        dst_crs=local,
        dst_nodata=1,
        resampling=Resampling.max,
    )
    earth[invalid != 0] = np.nan
    return match_local(earth), {
        "sources": sources,
        "body": "Earth",
        "source_family": "Copernicus GLO-30 DSM, public AWS COG distribution",
        "vertical_reference": "EGM2008, compared through relative shape only",
        "mask_buffer_m": buffer_m,
        "ancestry_status": "Filling/edit masks not present in this public COG acquisition; possible SRTM/other fill overlap prevents a fully independent truth claim",
        "license_source": "https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM",
    }


def validate(version="v5"):
    data = json.loads(
        (ROOT / f"apps/web/public/research/natural_land_{version}.json").read_text()
    )
    selected = [t for t in data["targets"] if t["id"].startswith("prospective")]
    results = []
    earth_cache = {}
    for buffer, experiment in data["experiments"].items():
        lookup = {c["id"]: c for c in experiment["candidates"]}
        for target in selected:
            pair = experiment["investigations"][target["id"]]
            stereo, _ = sample_stereo(
                ROOT / target["stereo_path"],
                target["latitude"],
                target["longitude"],
                3396190,
            )
            planetary = match_local(stereo)
            target_feature = fine_morphometry(planetary, 100)
            record = {
                "target_id": target["id"],
                "buffer_m": int(buffer),
                "frozen_pair": pair,
                "planetary": target_feature,
                "comparisons": {},
                "rehearsal_utility": "not_measured_no_fine_contact_reference_or_external_annotations",
            }
            for role in ["nomination", "control"]:
                cid = pair[role]
                if cid is None:
                    continue
                key = (cid, buffer)
                if key not in earth_cache:
                    candidate = lookup[cid]
                    region = next(
                        r for r in data["regions"] if r["id"] == candidate["region_id"]
                    )
                    grid, source = acquire_earth(
                        candidate, region, int(buffer), version
                    )
                    earth_cache[key] = (fine_morphometry(grid, 100), source)
                feature, source = earth_cache[key]
                record["comparisons"][role] = {
                    "candidate_id": cid,
                    "measurements": feature,
                    "distance": compare_fine(feature, target_feature),
                    "source": source,
                }
            results.append(record)
            print(
                target["id"],
                buffer,
                "diagnostic",
                list(record["comparisons"]),
                flush=True,
            )
    differences = []
    for row in results:
        if row["buffer_m"] != 1000 or set(row["comparisons"]) != {
            "nomination",
            "control",
        }:
            continue
        a, b = (
            row["comparisons"]["nomination"]["distance"],
            row["comparisons"]["control"]["distance"],
        )
        if a["joint_wasserstein"] is not None and b["joint_wasserstein"] is not None:
            differences.append(b["joint_wasserstein"] - a["joint_wasserstein"])
    output = {
        "natural_land_record_hash": data["record_hash"],
        "fine_analysis_spacing_m": 100,
        "results": results,
        "primary_complete_target_pairs": len(differences),
        "sign_test": paired_sign_test(differences),
        "randomization": paired_randomization(differences),
        "claim": "Incomplete paired design cannot establish superiority; nomination-only diagnostics are descriptive, not substituted controls",
        "reference_status": "No suitable independently authored fine contact lines or blinded human task labels acquired",
    }
    (ROOT / f"artifacts/reports/prospective_validation_{version}.json").write_text(
        json.dumps(output, indent=2, allow_nan=False), encoding="utf-8"
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--version", choices=["v5", "v6"], default="v5")
    validate(parser.parse_args().version)
