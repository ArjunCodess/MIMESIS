"""Acquire low-cloud independent Landsat scenes over frozen expansion regions."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import requests
import tifffile
from matplotlib.path import Path as PolygonPath

ROOT = Path(__file__).resolve().parents[1]


def download_scene(scene, token):
    folder = ROOT / "data/raw/earth/hls" / scene
    folder.mkdir(parents=True, exist_ok=True)
    base = f"https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/HLSL30.020/{scene}"
    public = base.replace("lp-prod-protected", "lp-prod-public")
    metadata_path = folder / f"{scene}_stac.json"
    if not metadata_path.exists():
        response = requests.get(f"{public}/{scene}_stac.json", timeout=40)
        response.raise_for_status()
        metadata_path.write_bytes(response.content)

    def band(name):
        path = folder / f"{scene}.{name}.tiff"
        if path.exists():
            return
        with requests.get(
            f"{base}/{scene}.{name}.tif",
            headers={"Authorization": f"Bearer {token}"},
            stream=True,
            timeout=(30, 120),
        ) as response:
            if response.status_code != 200:
                raise RuntimeError(
                    f"HLS {scene}/{name} returned HTTP {response.status_code}; token not logged"
                )
            temporary = path.with_suffix(".download.part")
            with temporary.open("wb") as stream:
                for block in response.iter_content(4 * 1024 * 1024):
                    stream.write(block)
        with tifffile.TiffFile(temporary) as raster:
            if raster.pages[0].shape != (3660, 3660):
                raise ValueError("Unexpected HLS raster shape")
            raster.pages[0].asarray()
        temporary.replace(path)

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(band, ["B02", "B03", "B04", "Fmask"]))
    print(f"{scene}: RGB and Fmask verified", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--token-file", type=Path, required=True)
    args = parser.parse_args()
    token = args.token_file.read_text(encoding="utf-8").strip()
    scenes = [
        "HLS.L30.T19KDQ.2025359T143108.v2.0",
        "HLS.L30.T19KDP.2025359T143108.v2.0",
        "HLS.L30.T19KEP.2025359T143108.v2.0",
    ]
    # Namib scenes are chosen by predeclared low-cloud metadata before v2 rankings.
    params = {
        "short_name": "HLSL30",
        "bounding_box": "15,-26,17,-24",
        "temporal": "2025-12-01T00:00:00Z,2025-12-31T23:59:59Z",
        "page_size": 200,
        "cloud_cover": "0,10",
    }
    response = requests.get(
        "https://cmr.earthdata.nasa.gov/search/granules.json", params=params, timeout=40
    )
    response.raise_for_status()
    metadata = response.json()
    (ROOT / "data/metadata/hls-namib-cmr.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    # Four tiles straddle the declared region's central meridians/latitude band.
    # Use scenes whose CMR bounding boxes intersect the four regional quadrants.
    selected = []
    for longitude, latitude in [
        (15.5, -24.15),
        (16.5, -24.15),
        (15.5, -24.5),
        (16.5, -24.5),
        (15.5, -25.5),
        (16.5, -25.5),
    ]:
        pool = []
        for entry in metadata["feed"]["entry"]:
            for polygon in entry.get("polygons", []):
                values = list(map(float, polygon[0].split()))
                vertices = list(zip(values[1::2], values[::2]))
                if PolygonPath(vertices).contains_point((longitude, latitude)):
                    pool.append(entry)
        if not pool:
            raise ValueError(
                f"No low-cloud HLS scene at declared Namib quadrant {longitude}, {latitude}"
            )
        selected.append(
            min(
                pool,
                key=lambda entry: (
                    float(entry.get("cloud_cover", 100)),
                    entry["title"],
                ),
            )["title"]
        )
    scenes += list(dict.fromkeys(selected))
    (ROOT / "data/metadata/hls-selected-scenes.json").write_text(
        json.dumps(
            {
                "selection": "Lowest cloud metadata per declared quadrant before v2 ranking",
                "scenes": scenes,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    for scene in scenes:
        download_scene(scene, token)
