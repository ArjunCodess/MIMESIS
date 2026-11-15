"""Acquire and measure Earth-only eligibility without ranking planetary targets."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import requests
import numpy as np
from rasterio.errors import RasterioError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from src.global_eligibility import (  # noqa: E402
    acquire_worldcover,
    atomic_json,
    buffered_natural,
    content_hash,
    metric_field,
    native_hls_mask,
    osm_mask,
    passes,
    prepare_osm,
    sha256,
    support_fractions,
    terrain_mask,
    worldcover_masks,
    inventory_hls,
    download_hls,
    inventory_osm,
    download_osm,
    probe_hls,
    masked_terrain_features,
)


def inputs():
    config = json.loads(
        (ROOT / "configs/global_eligibility_v9.json").read_text(encoding="utf-8")
    )
    frame = json.loads(
        (ROOT / "apps/web/public/research/global_frame_v6.json").read_text(
            encoding="utf-8"
        )
    )
    # Original record uses the project canonical JSON hash convention.
    from src.ranking import canonical_hash

    if (
        frame["frame_sha256"] != config["frame_sha256"]
        or canonical_hash({k: v for k, v in frame.items() if k != "frame_sha256"})
        != config["frame_sha256"]
    ):
        raise ValueError("Frozen frame hash mismatch")
    blocks = frame["blocks"]
    if len(blocks) != 100 or [b["id"] for b in blocks] != config["block_ids"]:
        raise ValueError("Must measure all100 frozen contexts in original order")
    return config, blocks


def acquire(config, blocks, workers):
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(acquire_worldcover, ROOT, b, config): b for b in blocks}
        for future in as_completed(futures):
            block = futures[future]
            # Acquisition is an external I/O boundary. Preserve errors and continue
            # the fixed frame so one unavailable source never selects the sample.
            try:
                record = future.result()
            except (
                OSError,
                ValueError,
                requests.RequestException,
                RasterioError,
            ) as error:
                record = {
                    "block_id": block["id"],
                    "status": "acquisition_failed",
                    "error_type": type(error).__name__,
                    "message": str(error),
                    "sources": [],
                }
                atomic_json(
                    ROOT
                    / f"data/raw/earth/global_eligibility_v9/{block['id']}/worldcover.json",
                    record,
                )
            print(block["id"], record["status"], len(record["sources"]), flush=True)


def measure(config, blocks, workers=2):
    implementation_snapshot = [
        sha256(ROOT / "src/global_eligibility.py"),
        sha256(Path(__file__)),
    ]
    osm = prepare_osm(ROOT, blocks, config)

    selected_hls = json.loads(
        (
            ROOT / "data/raw/earth/global_eligibility_v9/hls-acquisition-queue.json"
        ).read_text(encoding="utf-8")
    )

    def measure_one(block):
        block_scene_ids = {
            item["scene_id"]
            for item in selected_hls["scenes"]
            if block["id"] in item["blocks"]
        }
        field = metric_field(block, config)
        folder = ROOT / f"data/raw/earth/global_eligibility_v9/{block['id']}"
        source_path = (
            folder / config["worldcover"].get("source_revision", "") / "worldcover.json"
        )
        worldcover = (
            json.loads(source_path.read_text(encoding="utf-8"))
            if source_path.is_file()
            else {"status": "not_acquired", "sources": []}
        )
        source_binding = {
            "config": content_hash(config),
            "implementation_snapshot_v2": implementation_snapshot,
            "worldcover": worldcover,
            "osm": [
                {k: s[k] for k in ("id", "sha256", "counts")} for s in osm["sources"]
            ],
            "osm_index": osm["index_sha256"],
            "selected_hls_queue_sha256": sha256(
                ROOT / "data/raw/earth/global_eligibility_v9/hls-acquisition-queue.json"
            ),
            "hls_sources": [
                {
                    "path": p.relative_to(ROOT).as_posix(),
                    "bytes": p.stat().st_size,
                    "mtime_ns": p.stat().st_mtime_ns,
                }
                for p in sorted(
                    list((ROOT / "data/raw/earth/hls").rglob("*"))
                    + list(
                        (ROOT / "data/raw/earth/global_eligibility_v9/hls").rglob("*")
                    )
                )
                if p.is_file() and p.parent.name in block_scene_ids
            ],
            "terrain_inventory": [
                {
                    "path": str(p.relative_to(ROOT)),
                    "exists": p.is_file(),
                    "bytes": p.stat().st_size if p.is_file() else None,
                    "mtime_ns": p.stat().st_mtime_ns if p.is_file() else None,
                }
                for tile in block["nasadem_tiles"]
                for suffix in ["hgt", "swb", "num"]
                for p in [
                    ROOT / f"data/raw/earth/nasadem/NASADEM_HGT_{tile}/{tile}.{suffix}"
                ]
            ],
        }
        # Always verify retained clipped bytes before trusting a block checkpoint.
        clips_valid = all(
            (ROOT / s["path"]).is_file() and sha256(ROOT / s["path"]) == s["sha256"]
            for s in worldcover["sources"]
            if s["status"] == "acquired"
        )
        checkpoint = ROOT / f"data/processed/global_eligibility_v9/{block['id']}.json"
        # Native HLS sources and NASADEM inputs are bound below; on resume all
        # hashes are checked, so refreshed observations invalidate old gates.
        if checkpoint.is_file():
            cached = json.loads(checkpoint.read_text(encoding="utf-8"))
            bound = cached["source_binding"]
            external_sources = cached["bound_native_sources"]
            if (
                clips_valid
                and bound == source_binding
                and (ROOT / cached["mask_path"]).is_file()
                and sha256(ROOT / cached["mask_path"]) == cached["mask_sha256"]
                and all(
                    (ROOT / s["path"]).is_file()
                    and sha256(ROOT / s["path"]) == s["sha256"]
                    for s in external_sources
                )
                and content_hash(cached["block"]) == cached["block_sha256"]
            ):
                print(block["id"], "verified eligibility checkpoint", flush=True)
                return cached["block"]
        if not clips_valid:
            raise ValueError(
                f"WorldCover source checksum mismatch: {block['id']}; reacquire"
            )
        modified, unknown = worldcover_masks(ROOT, worldcover, field, config)
        worldcover_natural = buffered_natural(
            modified, unknown, config["spacing_m"], config["buffer_m"]
        )
        wc_fractions = support_fractions(worldcover_natural, config)
        wc_record = {
            "status": "measured_pass"
            if worldcover["status"] == "acquired"
            and passes(wc_fractions, config["natural_valid_minimum"])
            else "measured_insufficient_natural_land"
            if worldcover["status"] == "acquired"
            else "missing_or_incomplete_observations",
            **wc_fractions,
            "unknown": support_fractions(unknown, config),
            "sources": worldcover["sources"],
            "classification": "crop40/builtup50/permanent-water80; unknown native class invalid. Per-category max.500m buffer with conservative cell footprint allowance.",
        }
        roads, osm_record = osm_mask(field, osm)
        observed_modified = modified | roads if roads is not None else modified
        # This is an upper bound when OSM coverage is missing. It cannot yield
        # eligibility until the separate OSM coverage gate passes.
        natural = buffered_natural(
            observed_modified, unknown, config["spacing_m"], config["buffer_m"]
        )
        natural_fractions = support_fractions(natural, config)
        terrain, terrain_record, elevations = terrain_mask(ROOT, block, field, config)
        joint = terrain & natural
        joint_fractions = support_fractions(joint, config)
        masked_features, analysis_support, analysis_grids = masked_terrain_features(
            elevations, natural, config
        )
        masked_features_complete = all(
            value is not None for value in masked_features.values()
        )
        hls, hls_record = native_hls_mask(ROOT, block, field, config)
        v8_path = ROOT / f"data/processed/global_terrain_v8/{block['id']}.json"
        v8_measurement = json.loads(v8_path.read_text(encoding="utf-8"))["measurement"]
        terrain_record["frozen_v8_terrain_status"] = v8_measurement["status"]
        terrain_record["frozen_v8_analysis_context_valid_fractions"] = (
            v8_measurement.get("source_coverage") or {}
        ).get("analysis_context_valid_fractions")
        terrain_pass = (
            terrain_record["status"] == "measured_pass"
            and v8_measurement["status"] == "measured_all_tiers"
        )
        natural_pass = (
            passes(joint_fractions, config["natural_valid_minimum"])
            and masked_features_complete
        )
        osm_pass = osm_record["status"] == "measured_extract_coverage_complete"
        hls_pass = hls_record["status"] == "measured_pass"
        if worldcover["status"] != "acquired":
            state = "unknown_missing_required_layers"
        elif not terrain_pass:
            state = "excluded_terrain"
        elif not natural_pass:
            state = "excluded_observed_natural_land_upper_bound"
        elif not osm_pass or not hls_pass or worldcover["status"] != "acquired":
            state = "unknown_missing_required_layers"
        else:
            state = "eligible_under_mapped_sources"
        requests_ = []
        requests_.extend(
            {"layer": "osm", **r} for r in osm_record["acquisition_requests"]
        )
        if hls_record["acquisition_request"] is not None:
            requests_.append({"layer": "hls", **hls_record["acquisition_request"]})
        if worldcover["status"] != "acquired":
            requests_.append(
                {
                    "layer": "worldcover",
                    "reason": worldcover["status"],
                    "command": f"python scripts/build_global_eligibility.py --phase acquire --block {block['id']}",
                }
            )
        row = {
            "id": block["id"],
            "region_id": block["id"],
            "latitude": block["latitude"],
            "longitude": block["longitude"],
            "stratum": block["stratum"],
            "context_m": 80000,
            "window_m": 20000,
            "context_geometry": block["geometry"],
            "geometry": block["geometry"],
            "eligible": state == "eligible_under_mapped_sources",
            "status": state,
            "layers": {
                "terrain": terrain_record,
                "worldcover": wc_record,
                "osm": osm_record,
                "hls": hls_record,
            },
            "observed_natural_land_upper_bound": natural_fractions,
            "masked_terrain": joint_fractions,
            "masked_features": masked_features,
            "masked_analysis_support": analysis_support,
            "masked_features_status": "measured_all_tiers_under_mapped_sources"
            if masked_features_complete and osm_pass
            else "measured_upper_bound_missing_osm"
            if masked_features_complete
            else "excluded_insufficient_masked_analysis_support",
            "masked_features_contract": "Mapped natural/unknown mask applied to native-valid elevations before Gaussian smoothing;500m and1000m FWHM,>.999 valid weight, centered sampling, exact80km context/20km local,95percent primary support, V5/V6 eroded500m sensitivity. No target scores computed.",
            "missing_gate_reasons": [
                name
                for name, good in [
                    ("worldcover", worldcover["status"] == "acquired"),
                    ("osm", osm_pass),
                    ("hls", hls_pass),
                ]
                if not good
            ],
            "acquisition_requests": requests_,
            "limitation": "Observed mask fraction is an eligibility upper bound while any required source is missing. Mapped-source eligibility does not establish pristine land, access, geological equivalence or novelty.",
        }
        native_sources = [s for scene in hls_record["scenes"] for s in scene["sources"]]
        # Reuse the frozen V8 source digest inventory without reading target ranks.
        for tile in block["nasadem_tiles"]:
            for suffix in ["hgt", "swb", "num"]:
                p = ROOT / f"data/raw/earth/nasadem/NASADEM_HGT_{tile}/{tile}.{suffix}"
                if p.is_file():
                    native_sources.append(
                        {"path": p.relative_to(ROOT).as_posix(), "sha256": sha256(p)}
                    )
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        target = checkpoint.with_suffix(".npz")
        temporary = target.with_suffix(".tmp.npz")
        np.savez_compressed(
            temporary,
            observed_natural=natural,
            terrain=terrain,
            masked_terrain=joint,
            hls=hls,
            unknown_worldcover=unknown,
            masked_grid_500=analysis_grids["500"],
            masked_grid_1000=analysis_grids["1000"],
            spacing_m=config["spacing_m"],
            extent_m=field["size"] * config["spacing_m"],
        )
        temporary.replace(target)
        atomic_json(
            checkpoint,
            {
                "source_binding": source_binding,
                "bound_native_sources": native_sources,
                "block": row,
                "block_sha256": content_hash(row),
                "mask_path": target.relative_to(ROOT).as_posix(),
                "mask_sha256": sha256(target),
            },
        )
        print(
            block["id"],
            state,
            "land",
            joint_fractions,
            "OSM",
            osm_record["status"],
            "HLS",
            hls_record["status"],
            flush=True,
        )
        return row

    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(measure_one, blocks))
    summary = {
        "frozen_contexts": 100,
        "measured_contexts": len(rows),
        "eligible_contexts": sum(r["eligible"] for r in rows),
        "status_counts": dict(Counter(r["status"] for r in rows)),
        "layer_status_counts": {
            layer: dict(Counter(r["layers"][layer]["status"] for r in rows))
            for layer in ["terrain", "worldcover", "osm", "hls"]
        },
        "strata": {
            s: dict(Counter(r["status"] for r in rows if r["stratum"] == s))
            for s in ["BWh", "BWk"]
        },
        "per_region_counts": {
            r["id"]: {
                "context_count": 1,
                "eligible": int(r["eligible"]),
                "status": r["status"],
            }
            for r in rows
        },
    }
    result = {
        "id": config["id"],
        "schema_version": "1.0",
        "status": "completed_eligibility_inventory",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": config["scope"],
        "frame_sha256": config["frame_sha256"],
        "config_sha256": content_hash(config),
        "config": config,
        "summary": summary,
        "eligible_rule": "Exact frozen center and80km context. Both20km local and80km context require>=95percent native-valid terrain and>=95percent terrain intersected with buffered mapped natural-land before and after500/1000m Gaussian smoothing; all masked500/1000/eroded descriptor tiers must be measurable; complete available OSM distribution geometry/source decoding and>=95percent clear valid HLS in fixed date interval are required. Missing any required layer is unknown, never eligible.",
        "blocks": rows,
        "acquisition_queue": [
            {"block_id": r["id"], **q} for r in rows for q in r["acquisition_requests"]
        ],
        "source_index": {
            "path": "data/raw/earth/global_eligibility_v9/geofabrik-index-v1.json",
            "sha256": osm["index_sha256"],
        },
        "limitations": config["restrictions"]
        + [
            "OSM distribution coverage is geographic completeness of the downloaded extract, not verified completeness of actual roads/landuse.",
            "WorldCover aggregation/500m buffering conservatively excludes uncertain coarse-cell footprints.",
            "No descriptors or target scores recomputed; prior V8 ranks were already seen.",
        ],
    }
    result["record_hash"] = content_hash(result)
    markdown = (
        "\n".join(
            [
                "# Global eligibility V9",
                "",
                config["scope"],
                "",
                f"Measured {len(rows)}/100 frozen contexts; {summary['eligible_contexts']} eligible under all mapped-source gates.",
                "",
                "| Status | Contexts |",
                "|---|---:|",
            ]
            + [f"| {s} | {n} |" for s, n in summary["status_counts"].items()]
            + [
                "",
                "Missing OSM/HLS is unknown. Observed natural fractions remain upper bounds until required source coverage passes. No target comparisons or new ranks were computed.",
                "",
                "| Block | State | Masked terrain context | Masked terrain local | OSM | HLS |",
                "|---|---|---:|---:|---|---|",
            ]
            + [
                f"| {r['id']} | {r['status']} | {r['masked_terrain']['context_valid_fraction']:.4f} | {r['masked_terrain']['local_valid_fraction']:.4f} | {r['layers']['osm']['status']} | {r['layers']['hls']['status']} |"
                for r in rows
            ]
            + ["", "## Limitations", ""]
            + result["limitations"]
        )
        + "\n"
    )
    for folder in [ROOT / "artifacts/reports", ROOT / "apps/web/public/research"]:
        atomic_json(folder / "global_eligibility_v9.json", result)
        (folder / "global_eligibility_v9.md").write_text(markdown, encoding="utf-8")
    atomic_json(
        ROOT / "data/processed/global_eligibility_v9/acquisition_requests.json",
        result["acquisition_queue"],
    )
    print(json.dumps(summary), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        choices=[
            "acquire",
            "measure",
            "all",
            "inventory-hls",
            "acquire-hls",
            "inventory-osm",
            "acquire-osm",
            "probe-hls",
        ],
        default="all",
    )
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument(
        "--block",
        action="append",
        help="Retry acquisition for specified frozen IDs; never alters measurement membership",
    )
    parser.add_argument(
        "--max-scenes",
        type=int,
        default=1,
        help="Deterministic HLS prefix acquisition budget; does not change frame or eligibility rules",
    )
    parser.add_argument("--max-extracts", type=int, default=1)
    args = parser.parse_args()
    config, blocks = inputs()
    if args.phase == "probe-hls":
        probe_hls(ROOT)
    if args.phase == "inventory-osm":
        result = inventory_osm(ROOT, blocks, config, args.workers)
        print(
            json.dumps({k: v for k, v in result.items() if k != "sources"}), flush=True
        )
    if args.phase == "acquire-osm":
        download_osm(ROOT, config, args.max_extracts)
    if args.phase == "inventory-hls":
        result = inventory_hls(ROOT, blocks, config, args.workers)
        print(
            json.dumps({k: v for k, v in result.items() if k != "scenes"}), flush=True
        )
    if args.phase == "acquire-hls":
        download_hls(ROOT, config, args.max_scenes, args.workers)
    if args.phase in ["acquire", "all"]:
        selected = [b for b in blocks if not args.block or b["id"] in args.block]
        if args.block and set(args.block) - set(config["block_ids"]):
            parser.error("Unknown frozen block ID")
        acquire(config, selected, args.workers)
    if args.phase in ["measure", "all"]:
        measure(config, blocks, min(args.workers, 3))


if __name__ == "__main__":
    main()
