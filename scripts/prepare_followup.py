"""Freeze v6 acquisition, rebuild separate imagery coverage, and parse real OSM PBFs."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import osmium
from PIL import Image
from pyproj import CRS, Transformer
from rasterio.features import rasterize
from rasterio.transform import from_origin
from shapely import from_wkb, make_valid, transform
from shapely.geometry import LineString, box, mapping

from src.imagery import hls_context
from src.ranking import canonical_hash

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "apps/web/public/research"
REPORTS = ROOT / "artifacts/reports"
LAND_USE = {"farmland", "farmyard", "industrial", "quarry", "construction", "landfill"}
EXTRACTS = {
    "atacama": "chile",
    "namib": "namibia",
    "morocco": "morocco",
    "qaidam": "qinghai",
}


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class HumanFeatures(osmium.SimpleHandler):
    """Resolve ways and multipolygon relations before clipping to a metric field."""

    def __init__(self, forward):
        super().__init__()
        self.forward = forward
        self.factory = osmium.geom.WKBFactory()
        self.field = box(-116000, -116000, 116000, 116000)
        self.shapes = []
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
        xy = np.array([(n.lon, n.lat) for n in way.nodes])
        x, y = self.forward.transform(xy[:, 0], xy[:, 1])
        if (
            np.max(x) < -116000
            or np.min(x) > 116000
            or np.max(y) < -116000
            or np.min(y) > 116000
        ):
            return
        geometry = LineString(np.column_stack([x, y])).intersection(self.field)
        if not geometry.is_empty:
            self.shapes.append(geometry)
            self.counts["highways"] += 1

    def area(self, area):
        if area.tags.get("landuse") not in LAND_USE:
            return
        # Malformed external source geometry is recorded at its decoding boundary.
        try:
            geometry = from_wkb(self.factory.create_multipolygon(area))
        except (RuntimeError, osmium.InvalidLocationError):
            self.counts["invalid_areas"] += 1
            return
        projected = transform(
            make_valid(geometry), self.forward.transform, interleaved=False
        )
        if not projected.intersects(self.field):
            return
        self.shapes.append(projected.intersection(self.field))
        self.counts["landuse_areas"] += 1


def prepare():
    base = json.loads((PUBLIC / "discovery.json").read_text())
    protocol_path = ROOT / "configs/natural_land_v6.json"
    if not protocol_path.exists():
        protocol = json.loads((ROOT / "configs/natural_land_v5.json").read_text())
        protocol.update(
            id="mimesis-observable-natural-land-v6",
            parent="mimesis-natural-land-v5",
            frozen_at=datetime.now(timezone.utc).isoformat(),
        )
        protocol["scope"] = (
            "Exploratory eligibility follow-up; v5 outcomes already inspected, no untouched confirmatory claim. Thresholds and controls unchanged."
        )
        protocol["followup"] = {
            "imagery": "All locally acquired HLS scenes intersecting the full232km field; chronological then ID order, latest valid observation wins. Clear mask OR across scenes, exact source index retained.",
            "mask": "Existing WorldCover native class mask plus available PBF highways and assembled landuse areas, before smoothing. Missing OSM stays unknown as a source limitation.",
            "controls": "Same v5 physical tolerances and80km separation; zero swaps after finer evidence",
            "spatial_completeness": "Country/province extracts may omit adjacent jurisdictions and OSM is incomplete; no road-free or fully natural claim",
            "global_frame": "Separate sampled climate frame, never substituted into this bounded ranking",
            "scene_metadata_files": sorted(
                p.relative_to(ROOT).as_posix()
                for p in (ROOT / "data/raw/earth/hls").rglob("*stac.json")
            ),
        }
        protocol_path.write_text(json.dumps(protocol, indent=2), encoding="utf-8")
    overrides, regions = {}, []
    for region in base["regions"]:
        rid = region["id"]
        checkpoint = ROOT / f"data/processed/coverage-v6-{rid}.json"
        protocol_hash = canonical_hash(json.loads(protocol_path.read_text()))
        if checkpoint.exists():
            saved = json.loads(checkpoint.read_text())
            manifest_path = ROOT / f"data/raw/earth/human_masks_v6/{rid}/manifest.json"
            manifest = (
                json.loads(manifest_path.read_text())
                if manifest_path.exists()
                else None
            )
            mask_sources_valid = manifest is not None and all(
                (ROOT / source["regional_clip"]).is_file()
                and checksum(ROOT / source["regional_clip"]) == source["sha256"]
                for source in manifest["worldcover_sources"]
                if source["status"] == "acquired"
            )
            osm_source = manifest.get("osm_source") if manifest else None
            expected_osm = (
                ROOT / f"data/raw/earth/osm/{EXTRACTS.get(rid, rid)}-latest.osm.pbf"
            )
            if osm_source is not None:
                mask_sources_valid = (
                    mask_sources_valid
                    and expected_osm.is_file()
                    and checksum(expected_osm) == osm_source["sha256"]
                )
            elif rid in EXTRACTS and expected_osm.exists():
                mask_sources_valid = False
            if (
                mask_sources_valid
                and saved["protocol_hash"] == protocol_hash
                and all(
                    checksum(ROOT / s["path"]) == s["sha256"]
                    for s in saved["region"]["sources"]
                )
            ):
                overrides.update(saved["overrides"])
                regions.append(saved["region"])
                print(rid, "verified preparation checkpoint", flush=True)
                continue
        local = CRS.from_proj4(
            f"+proj=aeqd +lat_0={region['latitude']} +lon_0={region['longitude']} +datum=WGS84 +units=m"
        )
        inverse = Transformer.from_crs(local, 4326, always_xy=True)
        forward = Transformer.from_crs(4326, local, always_xy=True)
        edge = [
            inverse.transform(x, y)
            for x in np.linspace(-116000, 116000, 101)
            for y in [-116000, 116000]
        ] + [
            inverse.transform(x, y)
            for y in np.linspace(-116000, 116000, 101)
            for x in [-116000, 116000]
        ]
        west, south, east, north = (
            min(p[0] for p in edge),
            min(p[1] for p in edge),
            max(p[0] for p in edge),
            max(p[1] for p in edge),
        )
        records, sources = [], []
        mask = np.zeros((1856, 1856), dtype=bool)
        rgb = np.full((1856, 1856, 3), [230, 226, 214], dtype=np.uint8)
        source_index = np.zeros(mask.shape, dtype=np.uint16)
        scene_paths = []
        for name in json.loads(protocol_path.read_text())["followup"][
            "scene_metadata_files"
        ]:
            path = ROOT / name
            meta = json.loads(path.read_text())
            w, s, e, n = meta["bbox"]
            if e >= west and w <= east and n >= south and s <= north:
                scene_paths.append((meta["properties"]["datetime"], meta["id"], path))
        for index, (_, scene_id, path) in enumerate(sorted(scene_paths), 1):
            scene_image = PUBLIC / f"coverage-v6-{rid}-{scene_id}.png"
            good, record = hls_context(path.parent, inverse, scene_image, 232000)
            rgb[good] = np.asarray(Image.open(scene_image).convert("RGB"))[good]
            source_index[good] = index
            mask |= good
            records.append(record)
            sources.extend(
                {"path": f.relative_to(ROOT).as_posix(), "sha256": checksum(f)}
                for f in sorted(path.parent.iterdir())
                if f.suffix in {".tiff", ".json"}
            )
        Image.fromarray(rgb).save(PUBLIC / f"coverage-v6-{rid}.png")
        np.savez_compressed(
            ROOT / f"data/processed/{rid}-imagery-v6.npz",
            clear=mask,
            source_index=source_index,
        )
        for candidate in (c for c in base["candidates"] if c["region_id"] == rid):
            row = int((116000 - candidate["northing_m"]) / 125)
            col = int((116000 + candidate["easting_m"]) / 125)
            overrides[candidate["id"]] = {
                "reserved_hls_valid_fraction": float(
                    mask[row - 80 : row + 80, col - 80 : col + 80].mean()
                ),
                "hls_context_valid_fraction": float(
                    mask[row - 320 : row + 320, col - 320 : col + 320].mean()
                ),
                "imagery_scene_ids": [r["scene_id"] for r in records],
                "independent_image": f"coverage-v6-{rid}.png",
            }
        old_masks = np.load(ROOT / f"data/processed/{rid}-human-masks.npz")
        source_manifest = json.loads(
            (ROOT / f"data/raw/earth/human_masks/{rid}/manifest.json").read_text()
        )
        osm_path = ROOT / f"data/raw/earth/osm/{EXTRACTS.get(rid, rid)}-latest.osm.pbf"
        roads = np.zeros(mask.shape, dtype=bool)
        counts = {}
        if rid in EXTRACTS and osm_path.exists():
            handler = HumanFeatures(forward)
            handler.apply_file(str(osm_path), locations=True, idx="flex_mem")
            counts = handler.counts
            if handler.shapes:
                roads = rasterize(
                    [(mapping(g), 1) for g in handler.shapes],
                    out_shape=mask.shape,
                    transform=from_origin(-116000, 116000, 125, 125),
                    all_touched=True,
                    dtype="uint8",
                ).astype(bool)
            source_manifest.update(
                osm_status="acquired_pbf_country_or_province_extract",
                osm_source={
                    "path": osm_path.relative_to(ROOT).as_posix(),
                    "sha256": checksum(osm_path),
                },
                osm_features=counts,
            )
        source_manifest["followup_limit"] = (
            "OSM omissions, partial jurisdiction coverage and modern epoch remain; unflagged is not verified natural land."
        )
        folder = ROOT / f"data/raw/earth/human_masks_v6/{rid}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "manifest.json").write_text(
            json.dumps(source_manifest, indent=2), encoding="utf-8"
        )
        np.savez_compressed(
            ROOT / f"data/processed/{rid}-human-masks-v6.npz",
            classes=old_masks["classes"],
            roads=roads,
            spacing_m=125,
            extent_m=232000,
        )
        regions.append(
            {
                "region_id": rid,
                "scene_count": len(records),
                "clear_context_fraction": float(mask.mean()),
                "scenes": records,
                "osm": counts,
                "sources": sources,
                "osm_status": source_manifest["osm_status"],
            }
        )
        checkpoint.write_text(
            json.dumps(
                {
                    "protocol_hash": protocol_hash,
                    "region": regions[-1],
                    "overrides": {
                        c["id"]: overrides[c["id"]]
                        for c in base["candidates"]
                        if c["region_id"] == rid
                    },
                }
            ),
            encoding="utf-8",
        )
        print(rid, "coverage and PBF prepared", len(records), counts, flush=True)
    output = {
        "protocol": json.loads(protocol_path.read_text()),
        "base_record_hash": base["record_hash"],
        "regions": regions,
        "candidate_overrides": overrides,
    }
    output["record_hash"] = canonical_hash(output)
    (REPORTS / "coverage_v6.json").write_text(
        json.dumps(output, allow_nan=False), encoding="utf-8"
    )
    print("Frozen v6 source coverage; earlier records untouched", flush=True)


if __name__ == "__main__":
    prepare()
