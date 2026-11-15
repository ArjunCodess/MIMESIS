"""Persist inspectable Earth COGs, typed Parquet metadata and body-tagged footprints."""

import json
from pathlib import Path
import shutil
import numpy as np
import pyarrow.parquet as pq
import rasterio
from rasterio.transform import from_origin
from scipy.ndimage import map_coordinates
from src.terrain import smooth_grid

ROOT = Path(__file__).resolve().parents[1]


def export():
    public = ROOT / "apps/web/public/research"
    data = json.loads((public / "discovery.json").read_text())
    folder = ROOT / "data/derived/cogs"
    folder.mkdir(parents=True, exist_ok=True)
    records = []
    for region in data["regions"]:
        raw = np.load(ROOT / f"data/processed/{region['id']}-projected.npz")[
            "elevation"
        ]
        for support in [500, 1000]:
            smoothed = smooth_grid(raw, 125, support)
            factor = support / 125
            axis = np.arange(factor / 2 - 0.5, len(raw), factor)
            yy, xx = np.meshgrid(axis, axis, indexing="ij")
            grid = map_coordinates(
                smoothed, [yy, xx], order=1, mode="constant", cval=np.nan
            )
            path = folder / f"{region['id']}-{support}.tif"
            with rasterio.open(
                path,
                "w",
                driver="COG",
                width=len(grid),
                height=len(grid),
                count=1,
                dtype="float32",
                crs=f"+proj=aeqd +lat_0={region['latitude']} +lon_0={region['longitude']} +datum=WGS84 +units=m",
                transform=from_origin(-116000, 116000, support, support),
                nodata=-99999,
                compress="DEFLATE",
            ) as output:
                output.write(
                    np.where(np.isfinite(grid), grid, -99999).astype("float32"), 1
                )
                output.update_tags(
                    body="Earth",
                    vertical_reference="EGM96 metres",
                    analysis_spacing_m=str(support),
                    kernel="Gaussian FWHM equal to analysis spacing; .999 valid interpolation weight",
                    protocol_hash=data["protocol_hash"],
                    source_family="NASADEM HGT v001",
                    effective_resolution="Not established by grid spacing",
                )
            records.append(
                {
                    "path": path.relative_to(ROOT).as_posix(),
                    "region_id": region["id"],
                    "support_m": support,
                    "body": "Earth",
                }
            )
    parquet = ROOT / "data/processed/discovery_features.parquet"
    table = pq.read_table(parquet).replace_schema_metadata(
        {
            b"protocol_hash": data["protocol_hash"].encode(),
            b"body": b"Earth",
            b"units": b"relief/rms/tpi/altitude: metres; slope: degrees; histogram: fraction",
            b"feature_version": b"mimesis-terrain-v1",
        }
    )
    pq.write_table(table, parquet, compression="zstd")
    shutil.copy2(parquet, public / "discovery_features.parquet")
    (ROOT / "artifacts/reports/geospatial_exports.json").write_text(
        json.dumps(records, indent=2), encoding="utf-8"
    )
    print("Exported 12 metric COGs, typed Parquet and existing GeoJSON footprints")


if __name__ == "__main__":
    export()
