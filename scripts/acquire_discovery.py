"""Acquire the separately frozen six-region exploratory experiment, never rank it."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import requests
from matplotlib.path import Path as PolygonPath
from acquire_earth import acquire_tile
from acquire_hls import download_scene

ROOT = Path(__file__).resolve().parents[1]


def acquire(config_path, token_file, imagery):
    config = json.loads(config_path.read_text())
    token = token_file.read_text(encoding="utf-8").strip()
    tiles = sorted({t for r in config["regions"] for t in r["tiles"]})
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(
            pool.map(lambda tile: acquire_tile(tile, token, allow_missing=True), tiles)
        )
    if not imagery:
        return
    for region in config["regions"]:
        if region["id"] in {"atacama", "namib"}:
            continue
        response = requests.get(
            "https://cmr.earthdata.nasa.gov/search/granules.json",
            params={
                "short_name": "HLSL30",
                "bounding_box": ",".join(map(str, region["bounds"])),
                "temporal": "2025-06-01T00:00:00Z,2025-12-31T23:59:59Z",
                "page_size": 2000,
                "cloud_cover": "0,10",
            },
            timeout=90,
        )
        response.raise_for_status()
        metadata = response.json()
        (ROOT / f"data/metadata/hls-{region['id']}-discovery-cmr.json").write_text(
            json.dumps(metadata, indent=2), encoding="utf-8"
        )
        selected = set()
        missing = []
        # Freeze coverage locations before any ranking; minimize reported cloud, then ID.
        for dx in [-0.75, 0, 0.75]:
            for dy in [-0.75, 0, 0.75]:
                point = (region["longitude"] + dx, region["latitude"] + dy)
                pool = []
                for entry in metadata["feed"]["entry"]:
                    for polygon in entry.get("polygons", []):
                        values = list(map(float, polygon[0].split()))
                        if PolygonPath(
                            list(zip(values[1::2], values[::2]))
                        ).contains_point(point):
                            pool.append(entry)
                if pool:
                    selected.add(
                        min(
                            pool,
                            key=lambda e: (
                                float(e.get("cloud_cover", 100)),
                                e["title"],
                            ),
                        )["title"]
                    )
                else:
                    missing.append(point)
        (
            ROOT / f"data/metadata/hls-{region['id']}-discovery-selection.json"
        ).write_text(
            json.dumps(
                {
                    "rule": config["imagery_selection"],
                    "scenes": sorted(selected),
                    "uncovered_points": missing,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        for scene in sorted(selected):
            download_scene(scene, token)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "configs/discovery.json")
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--imagery", action="store_true")
    args = parser.parse_args()
    acquire(args.config, args.token_file, args.imagery)
