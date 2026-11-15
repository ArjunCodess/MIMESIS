"""Freeze new quality-selected stereo AOIs before computing any v5 Earth ranks."""

import hashlib
import json
from pathlib import Path
import requests
import numpy as np
from pyproj import Geod
from characterize_finer import sample_stereo
from src.ranking import canonical_hash

ROOT = Path(__file__).resolve().parents[1]


def select():
    config = json.loads((ROOT / "configs/natural_land_v5.json").read_text())
    rule = config["new_targets"]
    path = ROOT / "data/metadata/prospective-ctx-catalog.json"
    if not path.exists():
        response = requests.get(
            "https://stac.astrogeology.usgs.gov/api/search",
            params={
                "collections": rule["collection"],
                "bbox": ",".join(map(str, rule["bbox"])),
                "limit": rule["catalog_limit"],
            },
            timeout=90,
        )
        response.raise_for_status()
        path.write_text(json.dumps(response.json()), encoding="utf-8")
    catalog = json.loads(path.read_text())
    old = json.loads((ROOT / "apps/web/public/research/bundle.json").read_text())[
        "targets"
    ]
    used = [(t["longitude"], t["latitude"]) for t in old if t["body"] == "Mars"]
    geod = Geod(a=3396190, b=3396190)
    selected, excluded = [], []
    folder = ROOT / "data/raw/mars/prospective_stereo"
    folder.mkdir(parents=True, exist_ok=True)
    items = sorted(
        catalog["features"],
        key=lambda f: hashlib.sha256(("20261114" + f["id"]).encode()).hexdigest(),
    )
    for item in items:
        west, south, east, north = item["bbox"]
        longitude, latitude = (west + east) / 2, (south + north) / 2
        if not (0.5 < longitude < 89.5 and 0.5 < latitude < 43.5):
            excluded.append(
                {"id": item["id"], "reason": "Outside complete cached MOLA domain"}
            )
            continue
        if any(
            geod.inv(longitude, latitude, lon, lat)[2]
            < rule["minimum_separation_from_old_and_new_m"]
            for lon, lat in used
        ):
            excluded.append(
                {
                    "id": item["id"],
                    "reason": "Overlaps old or previously frozen new 80km context",
                }
            )
            continue
        # Geometry-only inexpensive check before acquiring a raster.
        if (
            geod.inv(west, latitude, east, latitude)[2] < 22000
            or geod.inv(longitude, south, longitude, north)[2] < 22000
        ):
            excluded.append(
                {
                    "id": item["id"],
                    "reason": "Stereo bounding box cannot contain 20km local window with smoothing buffer",
                }
            )
            continue
        url = item["assets"]["dtm"]["href"]
        dtm = folder / (item["id"] + ".tif")
        if not dtm.exists():
            response = requests.get(url, timeout=120)
            response.raise_for_status()
            dtm.write_bytes(response.content)
        grid, metadata = sample_stereo(dtm, latitude, longitude, 3396190)
        fraction = float(np.isfinite(grid[20:-20, 20:-20]).mean())
        if fraction < rule["local_stereo_minimum_valid_fraction"]:
            excluded.append(
                {
                    "id": item["id"],
                    "reason": "Local stereo validity below .95",
                    "valid_fraction": fraction,
                }
            )
            print(item["id"], "rejected coverage", fraction, flush=True)
            continue
        record = {
            "id": f"prospective-{len(selected) + 1:02d}",
            "name": f"Prospective CTX AOI {len(selected) + 1}",
            "body": "Mars",
            "latitude": latitude,
            "longitude": longitude,
            "split": "prospective_quality_selected",
            "source": "mola",
            "stereo_source_id": item["id"],
            "stereo_path": dtm.relative_to(ROOT).as_posix(),
            "stereo_url": url,
            "stereo_sha256": hashlib.sha256(dtm.read_bytes()).hexdigest(),
            "stereo_valid_fraction": fraction,
            "stereo_metadata": metadata,
            "orthoimage": item["assets"].get("orthoimage"),
            "selection_rule": "Fixed hash order, geometry, exclusion distance and measured validity only; no Earth rank or fine morphology used",
        }
        selected.append(record)
        used.append((longitude, latitude))
        (folder / (item["id"] + "-stac.json")).write_text(
            json.dumps(item, indent=2), encoding="utf-8"
        )
        print(record["id"], latitude, longitude, "frozen", flush=True)
        if len(selected) == rule["count"]:
            break
    output = {
        "protocol_hash": canonical_hash(config),
        "catalog_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "targets": selected,
        "excluded": excluded,
        "requested_count": rule["count"],
        "unfilled_count": rule["count"] - len(selected),
        "selection_status": "frozen_before_masked_Earth_ranking",
        "limitation": "Quality-selected subset of the retained catalogue query, not six random global Martian targets. No fine contact reference or independent relevance labels are assumed.",
    }
    (ROOT / "configs/prospective_targets_v5.json").write_text(
        json.dumps(output, indent=2), encoding="utf-8"
    )
    print(
        "Frozen",
        len(selected),
        "new targets;",
        output["unfilled_count"],
        "unfilled",
        flush=True,
    )


if __name__ == "__main__":
    select()
