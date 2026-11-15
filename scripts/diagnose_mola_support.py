"""Measure actual MOLA count-bin support; never invent individual PEDR shot tracks."""

import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from pyproj import CRS, Transformer
from scipy.ndimage import distance_transform_edt

ROOT = Path(__file__).resolve().parents[1]


def diagnose():
    path = ROOT / "data/raw/mars/mola/megc44n000hb.img"
    label = path.with_suffix(".xml")
    ns = {"p": "http://pds.nasa.gov/pds4/pds/v1"}
    image = ET.parse(label).find(".//p:Array_2D_Image", ns)
    shape = tuple(
        int(a.findtext("p:elements", namespaces=ns))
        for a in image.findall("p:Axis_Array", ns)
    )
    dtype = image.findtext("p:Element_Array/p:data_type", namespaces=ns)
    if (
        dtype != "UnsignedByte"
        or shape != (5632, 11520)
        or path.stat().st_size != int(np.prod(shape))
    ):
        raise ValueError(
            "Count product does not match the verified128ppd44N/0E unsigned-byte label"
        )
    counts = np.memmap(path, dtype="u1", mode="r", shape=shape)
    targets = json.loads(
        (ROOT / "apps/web/public/research/natural_land_v5.json").read_text()
    )["targets"]
    result = []
    axis = np.arange(-39750, 40000, 500)
    x, y = np.meshgrid(axis, -axis)
    for target in targets:
        if target["body"] != "Mars":
            continue
        crs = CRS.from_proj4(
            f"+proj=aeqd +lat_0={target['latitude']} +lon_0={target['longitude']} +R=3396000 +units=m"
        )
        inverse = Transformer.from_crs(
            crs, CRS.from_proj4("+proj=longlat +R=3396000"), always_xy=True
        )
        longitude, latitude = inverse.transform(x, y)
        rows = np.floor((44 - latitude) * 128).astype(int)
        cols = np.floor((longitude % 360) * 128).astype(int)
        values = counts[rows, cols]
        observed = values > 0
        distances = (
            distance_transform_edt(~observed, sampling=500) if observed.any() else None
        )
        result.append(
            {
                "target_id": target["id"],
                "analysis_spacing_m": 500,
                "local_zero_count_fraction": float(
                    np.mean(values[60:100, 60:100] == 0)
                ),
                "context_zero_count_fraction": float(np.mean(values == 0)),
                "maximum_in_window_distance_to_observed_bin_m": float(distances.max())
                if distances is not None
                else None,
                "interpretation": "Fraction of analysis-cell centers mapping to native bins with zero recorded observations; not independent shot count, true PEDR track positions or a calibrated effective-resolution estimate",
            }
        )
    output = {
        "source_url": "https://pds-geosciences.wustl.edu/mgs/urn-nasa-pds-mgs_mola_topography_derived/meg128/megc44n000hb.img",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "label_sha256": hashlib.sha256(label.read_bytes()).hexdigest(),
        "results": result,
        "limitation": "Individual PEDR shot coordinates were not acquired. Binned counts diagnose interpolation exposure but cannot recreate the MEGDR gridding kernel or establish symmetric cross-body support.",
    }
    (ROOT / "artifacts/reports/mola_support_v5.json").write_text(
        json.dumps(output, indent=2), encoding="utf-8"
    )
    print("Measured native count-bin support for", len(result), "Mars AOIs")


if __name__ == "__main__":
    diagnose()
