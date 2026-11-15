"""Acquire actual WorldCover class clips and OSM geometry before v5 ranking."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import requests
import numpy as np
import rasterio
from rasterio.windows import from_bounds, Window
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_origin
from rasterio.features import rasterize
from pyproj import CRS, Transformer
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]


class Point(BaseModel):
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lon: float = Field(ge=-180, le=180, allow_inf_nan=False)


class Way(BaseModel):
    id: int
    type: str
    geometry: list[Point] = []
    tags: dict[str, str] = {}


class Overpass(BaseModel):
    elements: list[Way]


def acquire_region(region):
    folder = ROOT / f"data/raw/earth/human_masks/{region['id']}"
    folder.mkdir(parents=True, exist_ok=True)
    output = ROOT / f"data/processed/{region['id']}-human-masks.npz"
    record_path = folder / "manifest.json"
    if output.exists() and record_path.exists():
        print(region["id"], "existing source-linked masks", flush=True)
        return
    extent, spacing = 232000, 125
    n = extent // spacing
    local = CRS.from_proj4(
        f"+proj=aeqd +lat_0={region['latitude']} +lon_0={region['longitude']} +datum=WGS84 +units=m"
    )
    inverse = Transformer.from_crs(local, "EPSG:4326", always_xy=True)
    forward = Transformer.from_crs("EPSG:4326", local, always_xy=True)
    corners = [
        inverse.transform(x, y) for x in [-116000, 116000] for y in [-116000, 116000]
    ]
    west, east = min(c[0] for c in corners), max(c[0] for c in corners)
    south, north = min(c[1] for c in corners), max(c[1] for c in corners)
    transform = from_origin(-116000, 116000, spacing, spacing)
    combined = np.zeros((n, n), dtype=np.uint8)
    covered = np.zeros((n, n), dtype=bool)
    sources = []
    for lat in range(math.floor(south / 3) * 3, math.floor(north / 3) * 3 + 1, 3):
        for lon in range(math.floor(west / 3) * 3, math.floor(east / 3) * 3 + 1, 3):
            tile = f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}{'E' if lon >= 0 else 'W'}{abs(lon):03d}"
            name = f"ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
            url = (
                "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
                + name
            )
            path = folder / name.replace("_Map.tif", "_regional_clip.tif")
            if not path.exists():
                header = requests.head(url, timeout=40)
                if header.status_code == 404:
                    sources.append({"url": url, "status": "HTTP_404"})
                    continue
                header.raise_for_status()
                with rasterio.Env(
                    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
                    GDAL_HTTP_TIMEOUT=90,
                ):
                    with rasterio.open(url) as source:
                        bbox = (
                            max(west, source.bounds.left),
                            max(south, source.bounds.bottom),
                            min(east, source.bounds.right),
                            min(north, source.bounds.top),
                        )
                        window = (
                            from_bounds(*bbox, transform=source.transform)
                            .round_offsets()
                            .round_lengths()
                            .intersection(Window(0, 0, source.width, source.height))
                        )
                        data = source.read(1, window=window)
                        profile = {
                            "driver": "GTiff",
                            "width": data.shape[1],
                            "height": data.shape[0],
                            "count": 1,
                            "dtype": "uint8",
                            "crs": source.crs,
                            "transform": source.window_transform(window),
                            "compress": "DEFLATE",
                            "tiled": True,
                        }
                        with rasterio.open(path, "w", **profile) as clipped:
                            clipped.write(data, 1)
                            clipped.update_tags(
                                source_url=url,
                                source_window=json.dumps(list(window.flatten())),
                                classification_version="WorldCover 2021 v200",
                                redistribution="CC BY 4.0; ESA WorldCover consortium",
                            )
            with rasterio.open(path) as source:
                classes = source.read(1)
                flags = np.where(
                    classes == 0, 2, np.isin(classes, [40, 50]).astype(np.uint8)
                ).astype(np.uint8)
                projected = np.full((n, n), 255, dtype=np.uint8)
                reproject(
                    flags,
                    projected,
                    src_transform=source.transform,
                    src_crs=source.crs,
                    dst_transform=transform,
                    dst_crs=local,
                    src_nodata=255,
                    dst_nodata=255,
                    resampling=Resampling.max,
                )
                valid = projected != 255
                combined[valid] = np.maximum(combined[valid], projected[valid])
                covered |= valid
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            sources.append(
                {
                    "url": url,
                    "regional_clip": path.relative_to(ROOT).as_posix(),
                    "sha256": digest,
                    "status": "acquired",
                }
            )
            print(region["id"], tile, "classification clip acquired", flush=True)
    combined[~covered] = 2
    osm_path = folder / "osm.json"
    osm_status = "not_acquired"
    if not osm_path.exists():
        query = f'[out:json][timeout:90];(way["highway"]({south},{west},{north},{east});way["landuse"~"^(farmland|industrial|quarry|construction|landfill)$"]({south},{west},{north},{east}););out geom;'
        for endpoint in [
            "https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter",
        ]:
            response = requests.post(endpoint, data={"data": query}, timeout=120)
            if response.status_code == 200 and "json" in response.headers.get(
                "content-type", ""
            ):
                parsed = Overpass.model_validate(response.json())
                osm_path.write_text(
                    json.dumps(
                        {
                            "endpoint": endpoint,
                            "query": query,
                            "elements": [e.model_dump() for e in parsed.elements],
                        }
                    ),
                    encoding="utf-8",
                )
                break
    shapes = []
    if osm_path.exists():
        parsed = Overpass.model_validate_json(osm_path.read_text())
        for way in parsed.elements:
            coordinates = [forward.transform(p.lon, p.lat) for p in way.geometry]
            if len(coordinates) < 2:
                continue
            polygon = (
                "highway" not in way.tags
                and len(coordinates) >= 4
                and coordinates[0] == coordinates[-1]
            )
            shapes.append(
                (
                    {"type": "Polygon", "coordinates": [coordinates]}
                    if polygon
                    else {"type": "LineString", "coordinates": coordinates},
                    1,
                )
            )
        osm_status = "acquired_geometries_not_completeness_verified"
    roads = (
        rasterize(
            shapes,
            out_shape=(n, n),
            transform=transform,
            fill=0,
            dtype="uint8",
            all_touched=True,
        ).astype(bool)
        if shapes
        else np.zeros((n, n), dtype=bool)
    )
    np.savez_compressed(
        output, classes=combined, roads=roads, spacing_m=spacing, extent_m=extent
    )
    record = {
        "region_id": region["id"],
        "worldcover_sources": sources,
        "osm_status": osm_status,
        "osm_features": len(shapes),
        "classification_rule": "Native WorldCover crop class40 and built-up50; any intersecting 10m flagged pixel marks the 125m analysis-mask cell. Class0/missing source is unknown, never natural.",
        "projection": local.to_wkt(),
        "classification_year": 2021,
        "ranking_dem_epoch": "SRTM acquisition in 2000 with NASADEM reprocessing/fill ancestry",
        "limitation": "Modern masks do not prove that human works existed during DEM acquisition. Cropland/build-up classification is fallible; OSM is incomplete and current. Missing OSM is disclosed, never equated with no roads.",
        "rights": "ESA WorldCover CC BY 4.0; OpenStreetMap contributors ODbL",
    }
    record_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(region["id"], "mask complete", osm_status, flush=True)


if __name__ == "__main__":
    config = json.loads((ROOT / "configs/discovery.json").read_text())
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(acquire_region, config["regions"]))
