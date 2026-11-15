"""Ingest a user-specified, already acquired physical context raster with a sidecar.

Manifest: metadata (ContextMetadata), raster_path, quality_mask_path, scale,
offset. Values are converted exactly once. Both rasters must share CRS/transform.
No arbitrary URL is fetched and no physical quantity is inferred from brightness.
"""

import argparse
import json
from pathlib import Path
import numpy as np
import rasterio
from pyproj import CRS
from pydantic import BaseModel, Field
from src.contexts import ContextMetadata, summarize_context


class Manifest(BaseModel):
    metadata: ContextMetadata
    raster_path: Path
    quality_mask_path: Path
    scale: float = Field(allow_inf_nan=False)
    offset: float = Field(allow_inf_nan=False)
    valid_quality_values: list[int] = Field(min_length=1)


def ingest(path, output):
    manifest = Manifest.model_validate_json(path.read_text())
    with (
        rasterio.open(path.parent / manifest.raster_path) as source,
        rasterio.open(path.parent / manifest.quality_mask_path) as quality,
    ):
        if source.crs is None:
            raise ValueError("A context raster requires an explicit body-specific CRS")
        radius = CRS.from_wkt(source.crs.to_wkt()).ellipsoid.semi_major_metre
        expected_radius = {"Earth": 6378137, "Mars": 3396190, "Moon": 1737400}[
            manifest.metadata.body
        ]
        if abs(radius - expected_radius) > 10000:
            raise ValueError("Context raster CRS and declared body do not agree")
        if (
            source.crs != quality.crs
            or source.transform != quality.transform
            or source.shape != quality.shape
        ):
            raise ValueError(
                "Quality and context rasters must have identical spatial registration"
            )
        raw = source.read(1)
        valid = (raw != source.nodata) & np.isin(
            quality.read(1), manifest.valid_quality_values
        )
        values = raw.astype(float) * manifest.scale + manifest.offset
        record = summarize_context(values, valid, manifest.metadata)
        record["crs"] = source.crs.to_wkt() if source.crs else None
        record["transform"] = list(source.transform)
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    ingest(args.manifest, args.output)
