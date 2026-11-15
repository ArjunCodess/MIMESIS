"""Target-blind land observability on the frozen 100-context Earth frame.

A source coverage pass means a complete downloaded extract, not complete OSM
mapping. This module never imports ranking or reads planetary outcomes.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np
import rasterio
from pyproj import CRS, Transformer
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.windows import Window, from_bounds
from rasterio.warp import reproject, Resampling
from scipy.ndimage import distance_transform_edt
from shapely.geometry import box, shape, mapping, LineString
from shapely import from_wkb, make_valid, transform as geometry_transform
import osmium
import requests


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def content_hash(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def metric_field(block: dict, config: dict) -> dict:
    spacing = config["spacing_m"]
    half = config["context_m"] / 2 + config["padding_m"]
    if config["padding_m"] < config["buffer_m"] + spacing * math.sqrt(2):
        raise ValueError("Padding must cover the buffer and both cell footprints")
    crs = CRS.from_proj4(
        f"+proj=aeqd +lat_0={block['latitude']} +lon_0={block['longitude']} +datum=WGS84 +units=m"
    )
    inverse = Transformer.from_crs(crs, 4326, always_xy=True)
    forward = Transformer.from_crs(4326, crs, always_xy=True)
    edge = [(x, y) for x in np.linspace(-half, half, 257) for y in [-half, half]] + [
        (x, y) for y in np.linspace(-half, half, 257) for x in [-half, half]
    ]
    lon, lat = inverse.transform(*np.asarray(edge).T)
    if np.ptp(lon) > 180:
        raise ValueError(
            "Antimeridian-spanning fields require split acquisition; frozen frame excludes them"
        )
    return {
        "crs": crs,
        "inverse": inverse,
        "forward": forward,
        "transform": from_origin(-half, half, spacing, spacing),
        "size": int(2 * half / spacing),
        "half": half,
        "bbox": (float(min(lon)), float(min(lat)), float(max(lon)), float(max(lat))),
    }


def native_flags(classes: np.ndarray, config: dict) -> tuple[np.ndarray, np.ndarray]:
    return np.isin(classes, config["worldcover"]["modified_classes"]).astype("uint8"), (
        ~np.isin(classes, config["worldcover"]["known_classes"])
    ).astype("uint8")


def buffered_natural(
    modified: np.ndarray, unknown: np.ndarray, spacing: float, buffer_m: float
) -> np.ndarray:
    # A flagged source may lie anywhere in its coarse cell, and an eligible cell
    # represents its full footprint. Two half diagonals bound this uncertainty.
    buffered = (
        distance_transform_edt(~modified, sampling=spacing)
        <= buffer_m + spacing * math.sqrt(2)
        if modified.any()
        else modified
    )
    return ~unknown & ~buffered


def support_fractions(mask: np.ndarray, config: dict) -> dict:
    n = config["context_m"] // config["spacing_m"]
    start = (len(mask) - n) // 2
    local_n = config["local_m"] // config["spacing_m"]
    local_start = (len(mask) - local_n) // 2
    return {
        "context_valid_fraction": float(
            mask[start : start + n, start : start + n].mean()
        ),
        "local_valid_fraction": float(
            mask[
                local_start : local_start + local_n, local_start : local_start + local_n
            ].mean()
        ),
    }


def passes(fractions: dict, minimum: float) -> bool:
    return min(fractions.values()) >= minimum


def _acquire_worldcover_box(
    root: Path, block: dict, config: dict, bbox=None, label="full", revision=""
) -> dict:
    field = metric_field(block, config)
    if bbox is not None:
        field["bbox"] = bbox
    folder = root / "data/raw/earth/global_eligibility_v9" / block["id"] / revision
    folder.mkdir(parents=True, exist_ok=True)
    sources = []
    west, south, east, north = field["bbox"]
    for lat in range(math.floor(south / 3) * 3, math.floor(north / 3) * 3 + 1, 3):
        for lon in range(math.floor(west / 3) * 3, math.floor(east / 3) * 3 + 1, 3):
            tile = f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}{'E' if lon >= 0 else 'W'}{abs(lon):03d}"
            name = f"ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
            url = (
                "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
                + name
            )
            suffix = "_clip.tif" if label == "full" else f"_{label}_clip.tif"
            path = folder / name.replace("_Map.tif", suffix)
            record_path = path.with_suffix(".source.json")
            if path.is_file() and record_path.is_file():
                record = json.loads(record_path.read_text(encoding="utf-8"))
                if record["sha256"] == sha256(path) and record["bbox"] == list(
                    field["bbox"]
                ):
                    sources.append(record)
                    continue
            response = requests.head(url, timeout=60)
            if response.status_code == 404:
                record = {
                    "url": url,
                    "status": "HTTP_404",
                    "tile": tile,
                    "bbox": list(field["bbox"]),
                }
                atomic_json(record_path, record)
                sources.append(record)
                continue
            response.raise_for_status()
            # Round outward, retaining every native cell touching the padded field.
            with rasterio.Env(
                GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
                GDAL_HTTP_TIMEOUT=90,
                GDAL_HTTP_MAX_RETRY=3,
            ):
                with rasterio.open(url) as source:
                    bounds = (
                        max(west, source.bounds.left),
                        max(south, source.bounds.bottom),
                        min(east, source.bounds.right),
                        min(north, source.bounds.top),
                    )
                    fractional = from_bounds(*bounds, transform=source.transform)
                    left, top = (
                        math.floor(fractional.col_off),
                        math.floor(fractional.row_off),
                    )
                    right, bottom = (
                        math.ceil(fractional.col_off + fractional.width),
                        math.ceil(fractional.row_off + fractional.height),
                    )
                    window = Window(left, top, right - left, bottom - top).intersection(
                        Window(0, 0, source.width, source.height)
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
                    temporary = path.with_suffix(".tmp.tif")
                    with rasterio.open(temporary, "w", **profile) as clipped:
                        clipped.write(data, 1)
                        clipped.update_tags(
                            source_url=url,
                            source_window=json.dumps(list(window.flatten())),
                            classification_version="WorldCover2021v200",
                            rights="ESA WorldCover consortium CC BY4.0",
                        )
                    temporary.replace(path)
            record = {
                "url": url,
                "tile": tile,
                "status": "acquired",
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
                "bbox": list(field["bbox"]),
                "native_window": list(window.flatten()),
                "acquired_at": datetime.now(timezone.utc).isoformat(),
            }
            atomic_json(record_path, record)
            sources.append(record)
    record = {
        "block_id": block["id"],
        "sources": sources,
        "status": "acquired"
        if all(s["status"] == "acquired" for s in sources)
        else "incomplete_source_coverage",
    }
    atomic_json(
        folder / ("worldcover.json" if label == "full" else f"worldcover-{label}.json"),
        record,
    )
    return record


def acquire_worldcover(root: Path, block: dict, config: dict) -> dict:
    revision = config["worldcover"].get("source_revision", "")
    if not revision:
        return _acquire_worldcover_box(root, block, config)
    folder = root / "data/raw/earth/global_eligibility_v9" / block["id"]
    original = json.loads((folder / "worldcover.json").read_text(encoding="utf-8"))
    if original["status"] != "acquired":
        raise ValueError(
            "Original82km WorldCover observations must be acquired before padding-only extension"
        )
    old_config = {**config, "padding_m": 1000}
    w0, s0, e0, n0 = metric_field(block, old_config)["bbox"]
    w, s, e, n = metric_field(block, config)["bbox"]
    strips = [
        ("padding_south", (w, s, e, s0)),
        ("padding_north", (w, n0, e, n)),
        ("padding_west", (w, s0, w0, n0)),
        ("padding_east", (e0, s0, e, n0)),
    ]
    sources = list(original["sources"])
    for label, bbox in strips:
        record = _acquire_worldcover_box(root, block, config, bbox, label, revision)
        sources.extend(record["sources"])
    record = {
        "block_id": block["id"],
        "status": "acquired"
        if all(s["status"] == "acquired" for s in sources)
        else "incomplete_source_coverage",
        "sources": sources,
        "extension": "Only geographic padding strips outside retained original82km envelope acquired; original sourceclips unchanged",
        "revision": revision,
    }
    atomic_json(folder / revision / "worldcover.json", record)
    return record


def worldcover_masks(
    root: Path, record: dict, field: dict, config: dict
) -> tuple[np.ndarray, np.ndarray]:
    dimensions = (field["size"], field["size"])
    modified, unknown, covered = (np.zeros(dimensions, dtype=bool) for _ in range(3))
    for entry in record["sources"]:
        if entry["status"] != "acquired":
            continue
        with rasterio.open(root / entry["path"]) as source:
            flags = native_flags(source.read(1), config)
            for native, destination in [
                (flags[0], modified),
                (flags[1], unknown),
                (np.ones(source.shape, dtype="uint8"), covered),
            ]:
                projected = np.full(dimensions, 255, dtype="uint8")
                reproject(
                    native,
                    projected,
                    src_transform=source.transform,
                    src_crs=source.crs,
                    dst_transform=field["transform"],
                    dst_crs=field["crs"],
                    resampling=Resampling.max,
                    init_dest_nodata=True,
                    dst_nodata=255,
                )
                destination |= projected == 1
    unknown |= ~covered
    return modified, unknown


class ExtractFeatures(osmium.SimpleHandler):
    """Decode the external PBF boundary once, retaining selected-context features."""

    def __init__(self, envelopes):
        super().__init__()
        self.envelopes = envelopes
        self.factory = osmium.geom.WKBFactory()
        self.features = []
        self.counts = {
            "highways": 0,
            "landuse_areas": 0,
            "incomplete_ways": 0,
            "invalid_areas": 0,
        }

    def way(self, way):
        if "highway" not in way.tags:
            return
        if len(way.nodes) < 2 or not all(n.location.valid() for n in way.nodes):
            self.counts["incomplete_ways"] += 1
            return
        xy = [(n.lon, n.lat) for n in way.nodes]
        geometry = LineString(xy)
        if any(geometry.intersects(b) for b in self.envelopes):
            self.features.append(
                {"geometry": mapping(geometry), "kind": "highway", "id": f"w{way.id}"}
            )
            self.counts["highways"] += 1

    def area(self, area):
        if area.tags.get("landuse") not in {
            "farmland",
            "farmyard",
            "industrial",
            "quarry",
            "construction",
            "landfill",
        }:
            return
        try:
            geometry = make_valid(from_wkb(self.factory.create_multipolygon(area)))
        except (RuntimeError, osmium.InvalidLocationError):
            self.counts["invalid_areas"] += 1
            return
        if any(geometry.intersects(b) for b in self.envelopes):
            self.features.append(
                {"geometry": mapping(geometry), "kind": "landuse", "id": f"a{area.id}"}
            )
            self.counts["landuse_areas"] += 1


def prepare_osm(root: Path, blocks: list[dict], config: dict) -> dict:
    folder = root / "data/raw/earth/global_eligibility_v9"
    index_path = folder / "geofabrik-index-v1.json"
    if not index_path.is_file():
        response = requests.get(config["osm"]["index_url"], timeout=90)
        response.raise_for_status()
        temporary = index_path.with_suffix(".tmp")
        temporary.write_bytes(response.content)
        temporary.replace(index_path)
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index_features = {f["properties"]["id"]: f for f in index["features"]}
    envelopes = [box(*metric_field(b, config)["bbox"]) for b in blocks]
    sources = []
    extract_paths = {
        identifier: root / f"data/raw/earth/osm/{identifier}-latest.osm.pbf"
        for identifier in config["osm"]["available_extracts"]
    }
    queue_path = folder / "osm-acquisition-queue.json"
    if queue_path.is_file():
        requests_ = json.loads(queue_path.read_text(encoding="utf-8"))
        extract_paths.update(
            {
                source["id"]: root / source["path"]
                for source in requests_["sources"]
                if (root / source["path"]).is_file()
            }
        )
    for identifier, path in sorted(extract_paths.items()):
        if not path.is_file():
            continue
        source_sha = sha256(path)
        target = folder / f"osm-{identifier}.json"
        if target.is_file():
            saved = json.loads(target.read_text(encoding="utf-8"))
            if (
                saved["sha256"] == source_sha
                and saved["frame_sha256"] == config["frame_sha256"]
            ):
                sources.append(saved)
                continue
        handler = ExtractFeatures(envelopes)
        handler.apply_file(str(path), locations=True, idx="flex_mem")
        record = {
            "id": identifier,
            "path": path.relative_to(root).as_posix(),
            "sha256": source_sha,
            "frame_sha256": config["frame_sha256"],
            "url": index_features[identifier]["properties"]["urls"]["pbf"],
            "jurisdiction_geometry": index_features[identifier]["geometry"],
            "counts": handler.counts,
            "features": handler.features,
            "spatial_completeness": "Geofabrik distribution polygon, not completeness of real-world mapping",
            "rights": "OpenStreetMap contributors ODbL",
        }
        atomic_json(target, record)
        print(identifier, "OSM decoded", handler.counts, flush=True)
        sources.append(record)
    return {
        "index_sha256": sha256(index_path),
        "index": index["features"],
        "sources": sources,
    }


def select_jurisdictions(features: list[dict], geographical) -> list[dict]:
    """Prefer actual covering country/province geometry over parent labels.

    Geofabrik states can have the same parent as their containing country;
    hierarchy strings cannot establish either containment or minimal requests.
    Continental and multi-country regional fallbacks are never requested.
    """
    from shapely.ops import unary_union

    regional = {
        "africa",
        "asia",
        "australia-oceania",
        "central-america",
        "europe",
        "north-america",
        "south-america",
        "us-west",
        "us-south",
        "us-midwest",
        "us-northeast",
        "us-pacific",
        "gcc-states",
        "south-africa-and-lesotho",
    }
    candidates = [
        f
        for f in features
        if f["properties"]["id"] not in regional
        and shape(f["geometry"]).intersection(geographical).area > 1e-12
    ]
    candidates.sort(key=lambda f: (shape(f["geometry"]).area, f["properties"]["id"]))
    # Coverage is tested in this exact field; no center-only jurisdiction lookup.
    selected = []
    covered = unary_union([])
    for feature in candidates:
        part = shape(feature["geometry"]).intersection(geographical)
        if not covered.buffer(1e-9).covers(part):
            selected.append(feature)
            covered = covered.union(part)
    # A parent needed for an uncovered part may make an earlier child redundant.
    for feature in sorted(
        selected.copy(), key=lambda f: shape(f["geometry"]).area, reverse=True
    ):
        others = unary_union(
            [shape(o["geometry"]) for o in selected if o is not feature]
        )
        if others.buffer(1e-9).covers(
            shape(feature["geometry"]).intersection(geographical)
        ):
            selected.remove(feature)
    return selected


def osm_mask(field: dict, osm: dict) -> tuple[np.ndarray | None, dict]:
    from shapely.ops import unary_union

    geographical = box(*field["bbox"])
    sources = [
        s
        for s in osm["sources"]
        if shape(s["jurisdiction_geometry"]).intersects(geographical)
    ]
    coverage = unary_union([shape(s["jurisdiction_geometry"]) for s in sources])
    source_complete = coverage.covers(geographical) and all(
        not s["counts"]["incomplete_ways"] and not s["counts"]["invalid_areas"]
        for s in sources
    )
    geometries = []
    for source in sources:
        for feature in source["features"]:
            geometry = shape(feature["geometry"])
            if geometry.intersects(geographical):
                projected = geometry_transform(
                    geometry, field["forward"].transform, interleaved=False
                ).intersection(
                    box(-field["half"], -field["half"], field["half"], field["half"])
                )
                if not projected.is_empty:
                    geometries.append((mapping(projected), 1))
    mask = (
        rasterize(
            geometries,
            out_shape=(field["size"], field["size"]),
            transform=field["transform"],
            all_touched=True,
            dtype="uint8",
        ).astype(bool)
        if geometries
        else np.zeros((field["size"], field["size"]), dtype=bool)
    )
    leaves = select_jurisdictions(osm["index"], geographical)
    available = {s["url"] for s in sources}
    requests_ = [
        {
            "id": f["properties"]["id"],
            "name": f["properties"]["name"],
            "url": f["properties"]["urls"]["pbf"],
            "jurisdiction": "Geofabrik distribution polygon in retained index",
            "reason": "Missing extract intersecting padded context",
        }
        for f in leaves
        if f["properties"]["urls"]["pbf"] not in available
    ]
    record = {
        "status": "measured_extract_coverage_complete"
        if source_complete
        else "missing_or_incomplete_jurisdiction_coverage",
        "sources": [
            {
                k: s[k]
                for k in (
                    "id",
                    "path",
                    "url",
                    "sha256",
                    "counts",
                    "spatial_completeness",
                )
            }
            for s in sources
        ],
        "intersecting_feature_count": len(geometries),
        "extract_coverage_fraction_bbox": float(
            coverage.intersection(geographical).area / geographical.area
        ),
        "acquisition_requests": requests_,
        "limitation": "Complete extract coverage cannot establish that all roads/landuse exist in OSM. No absence-of-human-modification claim.",
    }
    return mask if sources else None, record


def native_hls_mask(
    root: Path, block: dict, field: dict, config: dict
) -> tuple[np.ndarray, dict]:
    output = np.zeros((field["size"], field["size"]), dtype=bool)
    scenes = []
    requests_ = []
    queue_path = (
        root / "data/raw/earth/global_eligibility_v9/hls-acquisition-queue.json"
    )
    selected_queue = (
        json.loads(queue_path.read_text(encoding="utf-8"))
        if queue_path.is_file()
        else {"scenes": []}
    )
    selected_ids = {
        item["scene_id"]
        for item in selected_queue["scenes"]
        if block["id"] in item["blocks"]
    }
    for path in sorted(
        list((root / "data/raw/earth/hls").rglob("*stac.json"))
        + list((root / "data/raw/earth/global_eligibility_v9/hls").rglob("*stac.json"))
    ):
        if path.parent.name not in selected_ids:
            continue
        metadata = json.loads(path.read_text(encoding="utf-8"))
        if metadata["id"] not in selected_ids:
            continue
        date = metadata["properties"]["datetime"]
        if not config["hls"]["start"] <= date <= config["hls"]["end"]:
            continue
        if not box(*metadata["bbox"]).intersects(box(*field["bbox"])):
            continue
        files = {
            band: sorted(
                list(path.parent.glob(f"*{band}.tif"))
                + list(path.parent.glob(f"*{band}.tiff"))
            )
            for band in ["Fmask", "B02", "B03", "B04"]
        }
        if any(len(values) != 1 for values in files.values()):
            if len(files["Fmask"]) == 1:
                with rasterio.open(files["Fmask"][0]) as source:
                    values = source.read(1)
                if not ((values != 255) & ((values & 63) == 0)).any():
                    scenes.append(
                        {
                            "id": metadata["id"],
                            "datetime": date,
                            "status": "native_fmask_no_clear_pixels",
                            "rgb": "not checked because no native pixel can pass Fmask",
                            "valid_fractions": {
                                "context_valid_fraction": 0.0,
                                "local_valid_fraction": 0.0,
                            },
                            "sources": [
                                {
                                    "path": p.relative_to(root).as_posix(),
                                    "sha256": sha256(p),
                                }
                                for p in [path, files["Fmask"][0]]
                            ],
                        }
                    )
                    continue
            requests_.append(
                {
                    "scene_id": metadata["id"],
                    "reason": "Missing/ambiguous native bands or Fmask",
                    "required": ["B02", "B03", "B04", "Fmask"],
                }
            )
            continue
        with rasterio.open(files["Fmask"][0]) as source:
            fmask = source.read(1)
            valid = (fmask != 255) & ((fmask & config["hls"]["invalid_bits"]) == 0)
            native_coverage = np.ones(source.shape, dtype="uint8")
            source_transform, source_crs = source.transform, source.crs
        for band in ["B02", "B03", "B04"]:
            with rasterio.open(files[band][0]) as source:
                if (
                    source.shape != fmask.shape
                    or source.transform != source_transform
                    or source.crs != source_crs
                ):
                    raise ValueError(
                        f"HLS band/Fmask geometry mismatch: {metadata['id']}"
                    )
                valid &= (source.read(1) != -9999) & (source.read_masks(1) > 0)
        projected_coverage = np.zeros(output.shape, dtype="uint8")
        projected_invalid = np.ones(output.shape, dtype="uint8")
        for native, destination in [
            (native_coverage, projected_coverage),
            ((~valid).astype("uint8"), projected_invalid),
        ]:
            reproject(
                native,
                destination,
                src_transform=source_transform,
                src_crs=source_crs,
                dst_transform=field["transform"],
                dst_crs=field["crs"],
                resampling=Resampling.max,
                dst_nodata=255,
            )
        # Min coverage rejects target cells partly outside the native footprint.
        # Erode its native support one125m-cell equivalent before aggregation.
        from scipy.ndimage import binary_erosion

        native_interior = binary_erosion(
            native_coverage,
            iterations=math.ceil(config["spacing_m"] * math.sqrt(2) / 30),
        )
        interior = np.zeros(output.shape, dtype="uint8")
        reproject(
            native_interior.astype("uint8"),
            interior,
            src_transform=source_transform,
            src_crs=source_crs,
            dst_transform=field["transform"],
            dst_crs=field["crs"],
            resampling=Resampling.min,
            dst_nodata=0,
        )
        good = (projected_coverage == 1) & (interior == 1) & (projected_invalid == 0)
        output |= good
        scenes.append(
            {
                "id": metadata["id"],
                "datetime": date,
                "valid_fractions": support_fractions(good, config),
                "sources": [
                    {"path": p.relative_to(root).as_posix(), "sha256": sha256(p)}
                    for p in [path] + [v[0] for v in files.values()]
                ],
            }
        )
    fractions = support_fractions(output, config)
    status = (
        "measured_pass"
        if passes(fractions, config["hls_valid_minimum"])
        else "measured_insufficient_clear_coverage"
        if scenes
        else "missing_observations"
    )
    return output, {
        "status": status,
        **fractions,
        "scenes": scenes,
        "incomplete_scene_requests": requests_,
        "acquisition_request": {
            "short_name": "HLSL30",
            "version": "2.0",
            "temporal": f"{config['hls']['start']},{config['hls']['end']}",
            "bounding_box": list(field["bbox"]),
            "geometry": block["geometry"],
            "bands": ["B02", "B03", "B04", "Fmask"],
            "metadata": "STAC JSON per scene",
            "selection": config["hls"]["selection_policy"],
            "cmr_url": "https://cmr.earthdata.nasa.gov/search/granules.json",
            "authentication": "Protected assets require authorized Earthdata credential; no credential stored here",
        }
        if status != "measured_pass"
        else None,
    }


def terrain_mask(
    root: Path, block: dict, field: dict, config: dict
) -> tuple[np.ndarray, dict, np.ndarray]:
    from .terrain import Raster

    axis = np.arange(
        -field["half"] + config["spacing_m"] / 2, field["half"], config["spacing_m"]
    )
    x, y = np.meshgrid(axis, -axis)
    longitude, latitude = field["inverse"].transform(x, y)
    valid = np.zeros(x.shape, dtype=bool)
    missing = []
    elevations = np.full(x.shape, np.nan)
    for name in block["nasadem_tiles"]:
        south = int(name[1:3]) * (-1 if name[0] == "s" else 1)
        west = int(name[4:]) * (-1 if name[3] == "w" else 1)
        folder = root / f"data/raw/earth/nasadem_global_v6/NASADEM_HGT_{name}"
        if not folder.exists():
            # The frozen acquisition pipeline declares its actual shared cache.
            folder = root / f"data/raw/earth/nasadem/NASADEM_HGT_{name}"
        if not all(
            (folder / f"{name}.{suffix}").is_file()
            and (folder / f"{name}.{suffix}").stat().st_size == 3601 * 3601 * bytes_
            for suffix, bytes_ in [("hgt", 2), ("swb", 1), ("num", 1)]
        ):
            missing.append(name)
            continue
        inside = (
            (longitude >= west)
            & (longitude <= west + 1)
            & (latitude >= south)
            & (latitude <= south + 1)
        )
        if not inside.any():
            continue
        values = np.memmap(
            folder / f"{name}.hgt", dtype=">i2", mode="r", shape=(3601, 3601)
        )
        water = np.memmap(
            folder / f"{name}.swb", dtype="u1", mode="r", shape=(3601, 3601)
        )
        raster = Raster("nasadem", values, west, south + 1, 3600, 1, None, True, water)
        sampled = raster.sample(longitude[inside], latitude[inside])
        elevations[inside] = sampled
        valid[inside] = np.isfinite(sampled)
    fractions = support_fractions(valid, config)
    record = {
        "status": "missing_source_tiles"
        if missing
        else "measured_pass"
        if passes(fractions, config["terrain_valid_minimum"])
        else "measured_insufficient_valid_terrain",
        **fractions,
        "missing_tiles": missing,
        "support": "125m staging centers with all bilinear native HGT/SWB contributors valid. NUM required for source completeness. No smoothing or target descriptor calculation.",
    }
    return valid, record, elevations


def masked_terrain_features(
    elevations: np.ndarray, natural: np.ndarray, config: dict
) -> tuple[dict, dict, dict]:
    """Apply exclusion before Gaussian smoothing, then exact centered support."""
    from scipy.ndimage import map_coordinates
    from .terrain import smooth_grid, features

    if config["padding_m"] < 2000:
        raise ValueError(
            "Masked500/1000m support requires at least2km numerical padding"
        )
    half = len(elevations) * config["spacing_m"] / 2
    masked = np.where(natural, elevations, np.nan)
    measured, grids, support = {}, {}, {}
    for spacing in [500, 1000]:
        smoothed = smooth_grid(masked, config["spacing_m"], spacing)
        axis = np.arange(-40000 + spacing / 2, 40000, spacing)
        x, y = np.meshgrid(axis, -axis)
        grid = map_coordinates(
            smoothed,
            [
                (half - y) / config["spacing_m"] - 0.5,
                (x + half) / config["spacing_m"] - 0.5,
            ],
            order=1,
            mode="constant",
            cval=np.nan,
        )
        grids[str(spacing)] = grid
        measured[str(spacing)] = features(
            grid, spacing, minimum=config["terrain_valid_minimum"]
        )
        local_n = 20000 // spacing
        start = (len(grid) - local_n) // 2
        support[str(spacing)] = {
            "context_valid_fraction": float(np.isfinite(grid).mean()),
            "local_valid_fraction": float(
                np.isfinite(
                    grid[start : start + local_n, start : start + local_n]
                ).mean()
            ),
        }
    measured["eroded"] = features(
        grids["500"], 500, minimum=config["terrain_valid_minimum"], erode=True
    )
    return measured, support, grids


def inventory_hls(
    root: Path, blocks: list[dict], config: dict, workers: int = 4
) -> dict:
    """Retain public catalogue evidence before any protected image download."""
    from concurrent.futures import ThreadPoolExecutor

    folder = root / "data/raw/earth/global_eligibility_v9"

    def fetch(block):
        path = folder / block["id"] / "hls-cmr.json"
        if path.is_file():
            return block["id"], json.loads(path.read_text(encoding="utf-8"))
        params = {
            "short_name": "HLSL30",
            "version": "2.0",
            "bounding_box": ",".join(
                str(v) for v in metric_field(block, config)["bbox"]
            ),
            "temporal": f"{config['hls']['start']},{config['hls']['end']}",
            "page_size": 2000,
            "sort_key[]": ["start_date", "producer_granule_id"],
        }
        entries = []
        pages = []
        page = 1
        while True:
            response = requests.get(
                "https://cmr.earthdata.nasa.gov/search/granules.json",
                params={**params, "page_num": page},
                timeout=90,
            )
            response.raise_for_status()
            data = response.json()
            pages.append(data)
            entries.extend(data["feed"]["entry"])
            if len(data["feed"]["entry"]) < 2000:
                break
            page += 1
        record = {
            "query": params,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "pages": pages,
            "entries": entries,
            "status": "catalogue_complete",
        }
        atomic_json(path, record)
        print(block["id"], "HLS catalogue", len(entries), flush=True)
        return block["id"], record

    with ThreadPoolExecutor(max_workers=workers) as pool:
        observations = list(pool.map(fetch, blocks))
    scenes = {}
    for block_id, record in observations:
        for entry in record["entries"]:
            scene = entry["title"]
            if scene not in scenes:
                base = f"https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/HLSL30.020/{scene}"
                scenes[scene] = {
                    "scene_id": scene,
                    "datetime": entry["time_start"],
                    "catalogue_cloud_percent": float(entry.get("cloud_cover", 100)),
                    "blocks": [],
                    "reported_full_granule_MB": float(entry["granule_size"])
                    if entry.get("granule_size")
                    else None,
                    "metadata_url": base.replace("lp-prod-protected", "lp-prod-public")
                    + f"/{scene}_stac.json",
                    "files": [
                        {"band": b, "url": f"{base}/{scene}.{b}.tif"}
                        for b in ["B02", "B03", "B04", "Fmask"]
                    ],
                }
            scenes[scene]["blocks"].append(block_id)
    by_tile = {}
    for item in scenes.values():
        by_tile.setdefault(item["scene_id"].split(".")[2], []).append(item)
    for entries in by_tile.values():
        entries.sort(
            key=lambda item: (
                item["catalogue_cloud_percent"],
                item["datetime"],
                item["scene_id"],
            )
        )
        for position, item in enumerate(entries):
            item["tile_observation_order"] = position
    queue = sorted(
        [
            item
            for item in scenes.values()
            if item["tile_observation_order"]
            < config["hls"]["selected_scenes_per_mgrs_tile"]
        ],
        key=lambda item: (
            item["tile_observation_order"],
            item["scene_id"].split(".")[2],
        ),
    )
    result = {
        "config_sha256": content_hash(config),
        "scene_count": len(queue),
        "catalogue_scene_count": len(scenes),
        "unselected_catalogue_scene_count": len(scenes) - len(queue),
        "uncompressed_full_scene_selected_bands_upper_bound_bytes": len(queue)
        * 3660
        * 3660
        * 7,
        "band_file_count": 4 * len(queue),
        "sum_reported_full_granule_MB": sum(
            s["reported_full_granule_MB"] for s in queue
        )
        if all(s["reported_full_granule_MB"] is not None for s in queue)
        else None,
        "mgrs_tile_count": len(by_tile),
        "size_limitation": "CMR reported sizes describe full granules, not exact selected4band transfer. Source HEAD sizes are checked by the downloader.",
        "selection": config["hls"]["acquisition_order"],
        "scenes": queue,
    }
    atomic_json(folder / "hls-acquisition-queue.json", result)
    return result


def redirect_authorization(original_url: str, resolved_url: str, token: str) -> str:
    """Retain bearer authorization only within the original HTTPS origin."""
    from urllib.parse import urlsplit

    original, resolved = urlsplit(original_url), urlsplit(resolved_url)
    return (
        f"Authorization: Bearer {token}"
        if (original.scheme, original.hostname, original.port)
        == (resolved.scheme, resolved.hostname, resolved.port)
        and resolved.scheme == "https"
        else ""
    )


def resolve_hls_source(url: str, token: str) -> tuple[str, int, str]:
    from urllib.parse import urlsplit

    try:
        with requests.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Range": "bytes=0-0"},
            stream=True,
            timeout=(30, 120),
        ) as response:
            if response.status_code not in [200, 206]:
                raise ValueError(
                    f"Protected HLS archive returned HTTP{response.status_code}; token not logged"
                )
            return response.url, response.status_code, urlsplit(response.url).hostname
    except requests.RequestException as error:
        raise ValueError(
            f"HLS authorization probe failed: {type(error).__name__}; credentials and redirect URL not logged"
        ) from None


def probe_hls(root: Path) -> None:
    token = os.environ.get("EARTHDATA_TOKEN")
    if not token:
        raise ValueError("Set EARTHDATA_TOKEN in the process environment")
    queue = json.loads(
        (
            root / "data/raw/earth/global_eligibility_v9/hls-acquisition-queue.json"
        ).read_text(encoding="utf-8")
    )
    item = next(f for f in queue["scenes"][0]["files"] if f["band"] == "Fmask")
    _, status, host = resolve_hls_source(item["url"], token)
    print(json.dumps({"status": status, "final_hostname": host}), flush=True)


def download_hls(root: Path, config: dict, max_scenes: int, workers: int = 3) -> None:
    """Acquire native COG windows, Fmask first, from the frozen selected subset."""
    from rasterio.warp import transform_bounds
    from rasterio.errors import RasterioError

    token = os.environ.get("EARTHDATA_TOKEN")
    if not token:
        raise ValueError("Set EARTHDATA_TOKEN in the process environment")
    folder = root / "data/raw/earth/global_eligibility_v9"
    queue = json.loads(
        (folder / "hls-acquisition-queue.json").read_text(encoding="utf-8")
    )
    frame = json.loads(
        (root / "apps/web/public/research/global_frame_v6.json").read_text(
            encoding="utf-8"
        )
    )
    blocks = {b["id"]: b for b in frame["blocks"]}
    if queue["config_sha256"] != content_hash(config):
        raise ValueError("HLS inventory must match frozen config")

    def download_one(scene):
        directory = folder / "hls" / scene["scene_id"]
        directory.mkdir(parents=True, exist_ok=True)
        metadata_path = directory / f"{scene['scene_id']}_stac.json"
        if not metadata_path.is_file():
            response = requests.get(scene["metadata_url"], timeout=90)
            response.raise_for_status()
            atomic_json(metadata_path, response.json())
        fields = [
            metric_field(blocks[identifier], config)["bbox"]
            for identifier in scene["blocks"]
        ]
        geographical = (
            min(b[0] for b in fields),
            min(b[1] for b in fields),
            max(b[2] for b in fields),
            max(b[3] for b in fields),
        )
        for item in sorted(scene["files"], key=lambda entry: entry["band"] != "Fmask"):
            path = directory / f"{scene['scene_id']}.{item['band']}.tif"
            record_path = path.with_suffix(".source.json")
            if path.is_file() and record_path.is_file():
                record = json.loads(record_path.read_text(encoding="utf-8"))
                if record["sha256"] == sha256(path):
                    if item["band"] == "Fmask":
                        with rasterio.open(path) as source:
                            values = source.read(1)
                            if not ((values != 255) & ((values & 63) == 0)).any():
                                break
                    continue
            # The bearer header stays in process memory. GDAL errors containing
            # signed redirect URLs are replaced at this external I/O boundary.
            try:
                source_url, range_status, final_hostname = resolve_hls_source(
                    item["url"], token
                )
                with rasterio.Env(
                    GDAL_HTTP_HEADERS=redirect_authorization(
                        item["url"], source_url, token
                    ),
                    CPL_VSIL_CURL_USE_HEAD="NO",
                    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
                    GDAL_HTTP_TIMEOUT=120,
                    GDAL_HTTP_MAX_RETRY=3,
                ):
                    with rasterio.open(source_url) as source:
                        native_bounds = transform_bounds(
                            "EPSG:4326", source.crs, *geographical, densify_pts=41
                        )
                        fractional = from_bounds(
                            *native_bounds, transform=source.transform
                        )
                        left, top = (
                            math.floor(fractional.col_off),
                            math.floor(fractional.row_off),
                        )
                        right, bottom = (
                            math.ceil(fractional.col_off + fractional.width),
                            math.ceil(fractional.row_off + fractional.height),
                        )
                        window = Window(
                            left, top, right - left, bottom - top
                        ).intersection(Window(0, 0, source.width, source.height))
                        data = source.read(1, window=window)
                        profile = source.profile.copy()
                        profile.update(
                            driver="GTiff",
                            height=data.shape[0],
                            width=data.shape[1],
                            transform=source.window_transform(window),
                            compress="DEFLATE",
                            tiled=True,
                        )
                        temporary = path.with_suffix(".tmp.tif")
                        with rasterio.open(temporary, "w", **profile) as clipped:
                            clipped.write(data, 1)
                            clipped.update_tags(
                                source_url=item["url"],
                                source_window=json.dumps(list(window.flatten())),
                                role="native COG window preserving original HLS Fmask/band values and grid",
                            )
                        temporary.replace(path)
            except (
                requests.RequestException,
                RasterioError,
                OSError,
                ValueError,
            ) as error:
                import re

                status = re.search(
                    r"(?:HTTP response code[: ]*|HTTP error code[: ]*|HTTPError[: ]*|HTTP)(\d{3})",
                    str(error),
                )
                diagnostic = type(error).__name__ + (
                    f" HTTP{status.group(1)}" if status else ""
                )
                atomic_json(
                    directory / "acquisition_failure.json",
                    {
                        "scene_id": scene["scene_id"],
                        "band": item["band"],
                        "error_type": type(error).__name__,
                        "http_status": int(status.group(1)) if status else None,
                        "source_url": item["url"],
                        "state": "missing_native_observation",
                    },
                )
                raise ValueError(
                    f"HLS native window acquisition failed for {scene['scene_id']}/{item['band']}: {diagnostic}; authorization and redirect URLs not logged"
                ) from None
            record = {
                "url": item["url"],
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
                "source_window": list(window.flatten()),
                "source_grid": "Native HLS30m; clipped without resampling",
                "blocks": scene["blocks"],
                "acquired_at": datetime.now(timezone.utc).isoformat(),
            }
            atomic_json(record_path, record)
            if (
                item["band"] == "Fmask"
                and not ((data != 255) & ((data & 63) == 0)).any()
            ):
                atomic_json(
                    directory / "no_clear_fmask.json",
                    {
                        "status": "native_fmask_no_clear_pixels",
                        "rgb": "not requested because no native pixel can be clear",
                        "fmask": record,
                    },
                )
                break
        print(scene["scene_id"], "selected native window checkpoint", flush=True)

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=min(workers, 4)) as pool:
        list(pool.map(download_one, queue["scenes"][:max_scenes]))


def inventory_osm(
    root: Path, blocks: list[dict], config: dict, workers: int = 4
) -> dict:
    """Freeze the exact jurisdiction-extract set and public transfer sizes."""
    from concurrent.futures import ThreadPoolExecutor

    folder = root / "data/raw/earth/global_eligibility_v9"
    index_path = folder / "geofabrik-index-v1.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    selected = {}
    for block in blocks:
        field = box(*metric_field(block, config)["bbox"])
        leaves = select_jurisdictions(index["features"], field)
        for feature in leaves:
            identifier = feature["properties"]["id"]
            selected.setdefault(
                identifier,
                {
                    "id": identifier,
                    "url": feature["properties"]["urls"]["pbf"],
                    "blocks": [],
                    "jurisdiction_geometry": feature["geometry"],
                },
            )["blocks"].append(block["id"])

    def inspect(item):
        path = root / f"data/raw/earth/osm/{item['id']}-latest.osm.pbf"
        if path.is_file():
            return {
                **item,
                "status": "available_existing",
                "bytes": path.stat().st_size,
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256(path),
            }
        response = requests.head(item["url"], timeout=90)
        response.raise_for_status()
        size = (
            int(response.headers["Content-Length"])
            if response.headers.get("Content-Length")
            else None
        )
        if size is None:
            response = requests.get(
                item["url"], headers={"Range": "bytes=0-0"}, stream=True, timeout=90
            )
            if response.status_code == 206 and response.headers.get("Content-Range"):
                size = int(response.headers["Content-Range"].split("/")[-1])
            response.close()
        return {
            **item,
            "status": "request_ready" if size else "missing_size_metadata",
            "bytes": size,
            "path": f"data/raw/earth/global_eligibility_v9/osm/{item['id']}-latest.osm.pbf",
            "etag": response.headers.get("ETag"),
            "last_modified": response.headers.get("Last-Modified"),
        }

    with ThreadPoolExecutor(max_workers=workers) as pool:
        sources = list(
            pool.map(inspect, sorted(selected.values(), key=lambda s: s["id"]))
        )
    queue = [s for s in sources if s["status"] != "available_existing"]
    result = {
        "config_sha256": content_hash(config),
        "index_sha256": sha256(index_path),
        "extract_count": len(sources),
        "existing_extract_count": len(sources) - len(queue),
        "requested_extract_count": len(queue),
        "requested_total_bytes": sum(s["bytes"] for s in queue)
        if all(s["bytes"] is not None for s in queue)
        else None,
        "sources": sources,
        "limitation": "Geofabrik distribution geometry only. Source extract completeness cannot verify all physical roads/landuse are mapped. No global extract requested.",
    }
    atomic_json(folder / "osm-acquisition-queue.json", result)
    return result


def download_osm(root: Path, config: dict, max_extracts: int) -> None:
    folder = root / "data/raw/earth/global_eligibility_v9"
    queue = json.loads(
        (folder / "osm-acquisition-queue.json").read_text(encoding="utf-8")
    )
    if queue["config_sha256"] != content_hash(config):
        raise ValueError("OSM inventory must match frozen config")
    if queue["requested_total_bytes"] is None:
        raise ValueError("Public source byte counts must be known before downloading")
    print("Exact public OSM request bytes", queue["requested_total_bytes"], flush=True)
    for source in [s for s in queue["sources"] if s["status"] != "available_existing"][
        :max_extracts
    ]:
        path = root / source["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        record_path = path.with_suffix(".source.json")
        if path.is_file() and record_path.is_file():
            record = json.loads(record_path.read_text(encoding="utf-8"))
            if record["sha256"] == sha256(path):
                print(source["id"], "verified extract checkpoint", flush=True)
                continue
        partial = path.with_suffix(".part")
        offset = partial.stat().st_size if partial.is_file() else 0
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        with requests.get(
            source["url"], headers=headers, stream=True, timeout=(30, 120)
        ) as response:
            response.raise_for_status()
            if source["etag"] and response.headers.get("ETag") != source["etag"]:
                raise ValueError(
                    "Geofabrik mutable latest source changed; rerun inventory explicitly"
                )
            append = offset > 0 and response.status_code == 206
            with partial.open("ab" if append else "wb") as stream:
                for chunk in response.iter_content(4 * 1024 * 1024):
                    stream.write(chunk)
        if partial.stat().st_size != source["bytes"]:
            raise ValueError("Incomplete extract transfer; partial retained")
        partial.replace(path)
        atomic_json(
            record_path,
            {
                "url": source["url"],
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "rights": "OpenStreetMap contributors ODbL / Geofabrik",
            },
        )
        print(source["id"], "acquired", path.stat().st_size, flush=True)
