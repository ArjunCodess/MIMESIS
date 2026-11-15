"""Measure frozen v7 or v8 climate contexts from local NASADEM members."""

from collections import Counter
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time

import numpy as np
from src.ranking import canonical_hash, rank
from src.terrain import features, open_nasadem_mosaic, project_window

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

MEMBERS = {"hgt": 3601 * 3601 * 2, "swb": 3601 * 3601, "num": 3601 * 3601}
LIMITATIONS = [
    "Ten presampled 80 km contexts, one 20 km center window each; this is not the completed 100-block global terrain null or an estimate of global rarity.",
    "NASADEM HGT v001 is the same Earth source family as bounded v4; SWB water and HGT nodata are masked before smoothing. NUM records ancestry and is not a binary validity mask.",
    "WorldCover, current OSM and clear HLS gates are not complete for this pilot; no natural-land, absence-of-human-modification or clear-imagery eligibility claim is made.",
    "The twelve planetary targets reuse existing natural_land_v5 regional MOLA/LOLA descriptors, including six prospective targets. Prospective CTX stereo local support is not substituted into these regional descriptor scores.",
    "MOLA and LOLA interpolation, source support and epoch limitations remain. Shared descriptor support does not establish source independence or equivalent geology.",
    "Earth staging includes 2 km of smoothing padding on each side, cropped to the frozen 80 km analysis context. This boundary treatment is disclosed rather than asserted byte-identical to the exported baseline target tiers. The 125 m staging and 500/1000 m analysis spacing do not establish effective-resolution equivalence.",
    "The 0.35 engineering cutoff and finite support/weight/mask sensitivity set are descriptive, not calibrated relevance, discovery accuracy or a confidence interval. All target cases and measured ranks are retained.",
    "No geological corroboration, novelty audit, independent review, operational utility or new analogue discovery is established by this screening.",
]

CACHE_TRUST_LIMITS = {
    "stat_binding": (
        "Cached inspection is trusted without recomputing SHA256 or quality "
        "fractions only if on-disk member file sizes and modification timestamps (ns) "
        "match the checkpoint exactly."
    ),
    "schema_integrity": (
        "Checkpoint JSON must contain tile, stat_binding, record, and binding_sha256 keys."
    ),
    "cryptographic_binding": (
        "canonical_hash of {tile, stat_binding, record} must match binding_sha256."
    ),
    "invalidation_policy": (
        "Any change to file size, mtime, presence of members, or unavailable marker "
        "invalidates the checkpoint and forces fresh re-inspection."
    ),
    "reverification_policy": (
        "When reverify_checksums=True, file SHA256 digests are re-computed and verified "
        "against cached checksums to detect stealth byte-level modification."
    ),
}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_frozen_inputs(config, frame):
    content = {k: v for k, v in frame.items() if k != "frame_sha256"}
    if (
        canonical_hash(content) != frame["frame_sha256"]
        or frame["frame_sha256"] != config["frame_sha256"]
    ):
        raise ValueError("Frozen climate frame hash mismatch")
    counts = Counter()
    selected = []
    full_frame = config.get("selection_rule") == "all_frozen_blocks"
    for block in frame["blocks"]:
        if full_frame or counts[block["stratum"]] < 5:
            selected.append(block)
            counts[block["stratum"]] += 1
    expected = {"BWh": 50, "BWk": 50} if full_frame else {"BWh": 5, "BWk": 5}
    if [b["id"] for b in selected] != config["block_ids"] or counts != expected:
        raise ValueError(
            "Pilot must preserve the first five blocks in each frozen stratum"
        )
    if (
        sorted({tile for b in selected for tile in b["nasadem_tiles"]})
        != config["tiles"]
    ):
        raise ValueError(
            "Frozen acquisition tile list differs from selected block coverage"
        )
    if config["coverage_requirement"] != 0.95 or any(
        b["context_m"] != 80000 for b in selected
    ):
        raise ValueError(
            "Pilot requires the bounded 80 km context and 95 percent support contract"
        )
    return selected


def get_member_stats(directory: Path, tile: str) -> dict:
    stats = {}
    for suffix in MEMBERS:
        path = directory / f"{tile}.{suffix}"
        if path.is_file():
            st = path.stat()
            stats[suffix] = {
                "exists": True,
                "bytes": st.st_size,
                "mtime_ns": st.st_mtime_ns,
            }
        else:
            stats[suffix] = {
                "exists": False,
                "bytes": None,
                "mtime_ns": None,
            }
    marker_path = directory / "unavailable.json"
    if marker_path.is_file():
        st = marker_path.stat()
        stats["unavailable_marker"] = {
            "exists": True,
            "bytes": st.st_size,
            "mtime_ns": st.st_mtime_ns,
        }
    else:
        stats["unavailable_marker"] = {
            "exists": False,
            "bytes": None,
            "mtime_ns": None,
        }
    return stats


def save_tile_checkpoint(cache_dir: Path, tile: str, stats: dict, record: dict) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    target_path = cache_dir / f"{tile}.json"
    temp_path = cache_dir / f"{tile}.tmp.{os.getpid()}_{time.time_ns()}"
    payload = {
        "tile": tile,
        "stat_binding": stats,
        "record": record,
    }
    payload["binding_sha256"] = canonical_hash(
        {
            "tile": tile,
            "stat_binding": stats,
            "record": record,
        }
    )
    content = json.dumps(payload, indent=2, allow_nan=False)
    temp_path.write_text(content, encoding="utf-8")
    temp_path.replace(target_path)
    return target_path


def inspect_tile(
    raw: Path,
    tile: str,
    cache_dir: Path | None = None,
    trust_stat: bool = True,
    reverify_checksums: bool = False,
) -> dict:
    directory = raw / f"NASADEM_HGT_{tile}"
    stats = get_member_stats(directory, tile)

    if cache_dir is not None:
        checkpoint_path = cache_dir / f"{tile}.json"
        if checkpoint_path.is_file():
            try:
                cached = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                if (
                    isinstance(cached, dict)
                    and cached.get("tile") == tile
                    and "stat_binding" in cached
                    and "record" in cached
                    and "binding_sha256" in cached
                ):
                    expected_hash = canonical_hash(
                        {
                            "tile": tile,
                            "stat_binding": cached["stat_binding"],
                            "record": cached["record"],
                        }
                    )
                    if cached["binding_sha256"] == expected_hash:
                        if cached["stat_binding"] == stats:
                            if trust_stat and not reverify_checksums:
                                return cached["record"]
                            elif reverify_checksums:
                                valid = True
                                for m in cached["record"]["members"]:
                                    if m["status"] == "present":
                                        p = directory / m["name"]
                                        if not p.is_file() or digest(p) != m["sha256"]:
                                            valid = False
                                            break
                                if valid:
                                    return cached["record"]
            except Exception:
                pass

    members = []
    for suffix, expected in MEMBERS.items():
        path = directory / f"{tile}.{suffix}"
        size = path.stat().st_size if path.is_file() else None
        complete = size == expected
        members.append(
            {
                "name": path.name,
                "bytes": size,
                "expected_bytes": expected,
                "status": "present" if complete else "missing_or_incomplete",
                "sha256": digest(path) if complete else None,
            }
        )
    complete = all(m["status"] == "present" for m in members)
    record = {
        "tile": tile,
        "status": "members_present" if complete else "missing_or_incomplete",
        "remote_missing_marker": (directory / "unavailable.json").exists(),
        "members": members,
    }
    if complete:
        hgt = np.memmap(
            directory / f"{tile}.hgt", dtype=">i2", mode="r", shape=(3601, 3601)
        )
        swb = np.memmap(
            directory / f"{tile}.swb", dtype="u1", mode="r", shape=(3601, 3601)
        )
        num = np.memmap(
            directory / f"{tile}.num", dtype="u1", mode="r", shape=(3601, 3601)
        )
        codes, counts = np.unique(num, return_counts=True)
        record["native_quality"] = {
            "support": "Entire native tile including shared boundary nodes, not the selected footprint",
            "hgt_nodata_fraction": float(np.mean(hgt == -32768)),
            "swb_water_fraction": float(np.mean(swb == 255)),
            "num_code_counts": {
                str(int(code)): int(count) for code, count in zip(codes, counts)
            },
        }

    if cache_dir is not None:
        save_tile_checkpoint(cache_dir, tile, stats, record)

    return record


def inspect_sources(
    raw: Path,
    tiles: list[str],
    cache_dir: Path | None = None,
    trust_stat: bool = True,
    reverify_checksums: bool = False,
    max_workers: int = 4,
) -> list[dict]:
    if cache_dir is None:
        cache_dir = raw / ".inspection_cache"

    def _inspect(tile):
        return inspect_tile(
            raw,
            tile,
            cache_dir=cache_dir,
            trust_stat=trust_stat,
            reverify_checksums=reverify_checksums,
        )

    if max_workers and max_workers > 1 and len(tiles) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            return list(executor.map(_inspect, tiles))
    return [_inspect(tile) for tile in tiles]


def measure_block(block, raw, source_lookup):
    from scripts.build_research import tiers

    record = {
        "id": block["id"],
        "region_id": block["id"],
        "latitude": block["latitude"],
        "longitude": block["longitude"],
        "stratum": block["stratum"],
        "center_climate": block["center_climate"],
        "context_m": 80000,
        "window_m": 20000,
        "nasadem_tiles": block["nasadem_tiles"],
        "context_geometry": block["geometry"],
        "features": {"500": None, "1000": None, "eroded": None},
        "source_ids": ["nasadem"],
        "local_x_m": 0,
        "local_y_m": 0,
    }
    incomplete = [
        tile
        for tile in block["nasadem_tiles"]
        if source_lookup[tile]["status"] != "members_present"
    ]
    if incomplete:
        return {
            **record,
            "status": "excluded_incomplete_source_tiles",
            "missing_tiles": incomplete,
            "footprint": None,
            "source_coverage": None,
        }
    temp_dir = ROOT / "data/processed" if (ROOT / "data/processed").is_dir() else None
    with TemporaryDirectory(prefix="mimesis-global-pilot-", dir=temp_dir) as temporary:
        source = open_nasadem_mosaic(
            raw, block["nasadem_tiles"], Path(temporary) / "mosaic.hgt"
        )
        # The same 2 km smoothing padding as bounded planetary processing.
        # Only the frozen exact tile list is available; padding adds no new tiles.
        z, inverse = project_window(
            source, block["latitude"], block["longitude"], 84000, 125
        )
        _, grids = tiers(z)
        grids = {"500": grids["500"][4:-4, 4:-4], "1000": grids["1000"][2:-2, 2:-2]}
        measured = {tier: features(grid, int(tier)) for tier, grid in grids.items()}
        measured["eroded"] = features(grids["500"], 500, erode=True)
        valid = np.isfinite(z[16:-16, 16:-16])
        local = valid[240:400, 240:400]
        record["source_coverage"] = {
            "support": "125 m projected staging cells in frozen 80 km context before analysis smoothing; a 2 km numerical padding uses only the exact frozen tiles",
            "context_valid_fraction": float(valid.mean()),
            "local_valid_fraction": float(local.mean()),
            "context_masked_fraction": float(1 - valid.mean()),
            "analysis_context_valid_fractions": {
                tier: float(np.isfinite(grid).mean()) for tier, grid in grids.items()
            },
        }
        record["features"] = measured
        record["footprint"] = [
            list(inverse.transform(x, y))
            for x, y in [
                (-10000, -10000),
                (10000, -10000),
                (10000, 10000),
                (-10000, 10000),
                (-10000, -10000),
            ]
        ]
        record["projection"] = (
            f"WGS84 AEQD centered {block['latitude']}, {block['longitude']}; local coordinates belong only to {block['id']}"
        )
        # Close Windows-backed maps before the temporary directory is removed.
        del source
    record["status"] = (
        "measured_all_tiers"
        if all(measured.values())
        else "excluded_water_or_nodata_coverage"
    )
    record["excluded_tiers"] = [
        tier for tier, feature in measured.items() if feature is None
    ]
    return record


def build(config_path=None):
    config_path = config_path or ROOT / "configs/global_terrain_v7.json"
    config_sha256 = digest(config_path)
    config = json.loads(config_path.read_text())
    stem = config.get("output_stem", "global_terrain_v7")
    if stem not in {"global_terrain_v7", "global_terrain_v8"}:
        raise ValueError("Unknown frozen experiment output stem")
    limits = list(LIMITATIONS)
    if stem == "global_terrain_v8":
        limits[0] = (
            "All 100 frozen climate contexts, one 20 km center per 80 km context. Only source-valid terrain contributes to ranks; no global rarity, complete natural-land or geological validity claim."
        )
    frame = json.loads(
        (ROOT / "apps/web/public/research/global_frame_v6.json").read_text()
    )
    selected = validate_frozen_inputs(config, frame)
    target_path = ROOT / "apps/web/public/research/natural_land_v5.json"
    target_bundle = json.loads(target_path.read_text())
    targets = target_bundle["targets"]
    if len(targets) != 12 or len({t["id"] for t in targets}) != 12:
        raise ValueError("Expected all six old and six prospective targets")
    original = target_bundle["protocol"]
    protocol = {
        k: original[k]
        for k in (
            "weights",
            "groups",
            "tolerances",
            "provisional_maximum_loss",
            "scenario_seed",
            "random_weight_scenarios",
        )
    }
    protocol.update(
        {
            "id": config["id"],
            "task": "regional_geomorphological_mapping",
            "window_m": 20000,
            "context_m": 80000,
            "supports_m": [500, 1000],
            "minimum_valid_fraction": 0.95,
            "staging_step_m": 125,
            "smoothing_padding_per_side_m": 2000,
            "projected_extent_with_padding_m": 84000,
            "padding_source_contract": "Only the exact frozen block tile list; crop after smoothing to 80 km context",
            "support_interpretation": "Analysis spacing and descriptor family, not verified effective source resolution",
        }
    )
    raw = ROOT / "data/raw/earth/nasadem"
    source_records = inspect_sources(raw, config["tiles"])
    lookup = {s["tile"]: s for s in source_records}
    blocks = []
    for block in selected:
        checkpoint = ROOT / "data/processed" / stem / (block["id"] + ".json")
        binding = canonical_hash(
            {
                "config": config_sha256,
                "frame": frame["frame_sha256"],
                "implementation": digest(Path(__file__)),
                "sources": [lookup[t] for t in block["nasadem_tiles"]],
            }
        )
        cached = json.loads(checkpoint.read_text()) if checkpoint.exists() else None
        if cached is not None and cached["binding"] == binding:
            measured = cached["measurement"]
        else:
            measured = measure_block(block, raw, lookup)
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            temp_ckpt = checkpoint.with_suffix(f".tmp.{os.getpid()}_{time.time_ns()}")
            temp_ckpt.write_text(
                json.dumps(
                    {"binding": binding, "measurement": measured}, allow_nan=False
                ),
                encoding="utf-8",
            )
            temp_ckpt.replace(checkpoint)
        blocks.append(measured)
        print(f"{block['id']}: {blocks[-1]['status']}", flush=True)
    candidates = [b for b in blocks if b["status"] == "measured_all_tiers"]
    rankings = {t["id"]: rank(blocks, t, protocol, 500) for t in targets}
    rankings_1000 = {t["id"]: rank(blocks, t, protocol, 1000) for t in targets}
    summaries = []
    for target in targets:
        result = rankings[target["id"]]
        rows = result["candidates"]
        passes = [r for r in rows if r["passes_provisional_threshold"]]
        summaries.append(
            {
                "target_id": target["id"],
                "name": target["name"],
                "body": target["body"],
                "cohort": "prospective"
                if target["id"].startswith("prospective-")
                else "previously_inspected",
                "state": result["state"],
                "cutoff_state": "passes_descriptive_cutoff"
                if passes
                else "no_measured_candidate_passes_cutoff"
                if rows
                else "no_eligible_terrain",
                "passing_count": len(passes),
                "eligible_count": len(rows),
                "leader": rows[0] if rows else None,
                "leader_1000": next(
                    iter(rankings_1000[target["id"]]["candidates"]), None
                ),
                "excluded_blocks": [
                    {"id": b["id"], "status": b["status"]}
                    for b in blocks
                    if b["status"] != "measured_all_tiers"
                ],
            }
        )
    if digest(config_path) != config_sha256:
        raise ValueError("Frozen pilot config changed while measuring")
    bundle = {
        "id": config["id"],
        "schema_version": "1.0",
        "status": "exploratory_source_consistent_regional_descriptor_screening",
        "frame_sha256": frame["frame_sha256"],
        "config_sha256": config_sha256,
        "config": config,
        "target_input": {
            "path": "apps/web/public/research/natural_land_v5.json",
            "sha256": digest(target_path),
            "record_hash": target_bundle["record_hash"],
            "descriptor_role": "Regional MOLA/LOLA features reused without fitting",
        },
        "summary": {
            "frozen_block_count": len(selected),
            "measured_block_count": len(candidates),
            "excluded_block_count": len(blocks) - len(candidates),
            "stratum_counts": dict(Counter(b["stratum"] for b in selected)),
            "measured_stratum_counts": dict(Counter(b["stratum"] for b in candidates)),
            "target_count": len(targets),
            "unique_tile_count": len(source_records),
            "complete_tile_count": sum(
                s["status"] == "members_present" for s in source_records
            ),
            "targets_with_descriptive_cutoff_pass": sum(
                t["passing_count"] > 0 for t in summaries
            ),
        },
        "protocol": protocol,
        "protocol_hash": canonical_hash(protocol),
        "targets": targets,
        "blocks": blocks,
        "candidates": candidates,
        "source_coverage": source_records,
        "rankings": rankings,
        "rankings_1000": rankings_1000,
        "target_summaries": summaries,
        "limitations": limits,
        "claim": config["claim"],
    }
    bundle["record_hash"] = canonical_hash(bundle)
    for path in [
        ROOT / f"apps/web/public/research/{stem}.json",
        ROOT / f"artifacts/reports/{stem}.json",
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(bundle, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
    lines = [
        f"# Global terrain experiment {stem}",
        "",
        config["claim"],
        "",
        f"Measured {len(candidates)} of {len(selected)} frozen contexts with complete 500 m, 1000 m and eroded descriptors, using {bundle['summary']['complete_tile_count']} of {len(source_records)} complete native NASADEM tiles. Every block retains its original ID and every target case remains published.",
        "",
        "Each 80 km context is projected at 125 m numerical staging, with the same Gaussian support matching and 20 km center descriptors as bounded v4. SWB water and HGT nodata are excluded before smoothing; missing tiles exclude the block. NUM is retained as ancestry metadata. Regional scores reuse the twelve existing MOLA/LOLA target descriptors; fine CTX stereo does not enter these scores.",
        "",
        "| Target | Leader | Robust loss | Passing / eligible | Cutoff state |",
        "|---|---|---:|---:|---|",
    ]
    for result in summaries:
        leader = result["leader"]
        loss = f"{leader['robust_loss']:.6f}" if leader else "unavailable"
        lines.append(
            f"| {result['name']} | {leader['id'] if leader else 'none'} | {loss} | {result['passing_count']} / {result['eligible_count']} | {result['cutoff_state']} |"
        )
    lines += ["", "## Source exclusions", ""]
    lines += [
        f"- {b['id']}: {b['status']}; staging context coverage {b['source_coverage']['context_valid_fraction']:.4f}."
        if b["source_coverage"]
        else f"- {b['id']}: {b['status']}; missing tiles {b.get('missing_tiles', [])}."
        for b in blocks
    ]
    lines += ["", "## Limits", ""] + [f"- {limit}" for limit in limits]
    lines += [
        "",
        f"Climate frame SHA256 `{bundle['frame_sha256']}`. Pilot config SHA256 `{config_sha256}`. Record SHA256 `{bundle['record_hash']}`.",
        "",
        f"The full JSON contains native member checksums, whole-tile water/nodata/NUM summaries, projected source support, all descriptors, both complete support rankings, leaders and exclusions. Reproduce with `python scripts/measure_global_pilot.py --config configs/{stem}.json` after acquisition of the frozen tile manifest.",
    ]
    for path in [
        ROOT / f"artifacts/reports/{stem}.md",
        ROOT / f"apps/web/public/research/{stem}.md",
    ]:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(bundle["summary"], indent=2))
    return bundle


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=ROOT / "configs/global_terrain_v7.json"
    )
    build(parser.parse_args().config)
