"""Build a distinct exploratory experiment while preserving the released v3 record."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from scipy.ndimage import map_coordinates
from scipy.stats import spearmanr

from build_research import terrain_image, tiers
from measure_regions import measure_regions
from src.ranking import canonical_hash, rank
from src.selection import freeze_shortlist
from src.suites import subwindows, requirement_coverage, select_suite
from src.terrain import open_pds, project_window, smooth_grid

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "apps/web/public/research"
REPORTS = ROOT / "artifacts/reports"


def extract_subwindows(grids):
    result = {tier: subwindows(grid, int(tier)) for tier, grid in grids.items()}
    eroded = grids["500"].copy()
    start = (len(eroded) - 40) // 2
    eroded[start, start : start + 40] = np.nan
    eroded[start + 39, start : start + 40] = np.nan
    eroded[start : start + 40, start] = np.nan
    eroded[start : start + 40, start + 39] = np.nan
    result["eroded"] = subwindows(eroded, 500)
    return result


def build(fresh=False):
    baseline = json.loads((PUBLIC / "bundle.json").read_text())
    config = json.loads((ROOT / "configs/discovery.json").read_text())
    contracts = json.loads((ROOT / "configs/task_contracts.json").read_text())
    protocol = {
        **baseline["protocol"],
        "id": config["id"],
        "parent_protocol": config["parent_protocol"],
        "regions": config["regions"],
        "evaluation_status": config["status"],
        "task_contracts": contracts,
    }
    protocol["scope_deviations"] = [
        config["status"],
        "All candidate regions already have planetary analogue literature; no new-region claim",
        "No external relevance labels; no discovery accuracy or campaign-performance estimate",
    ]
    frozen = {
        "protocol": protocol,
        "protocol_hash": canonical_hash(protocol),
        "frozen_at": config["frozen_at"],
    }
    (REPORTS / "discovery_protocol.json").write_text(
        json.dumps(frozen, indent=2), encoding="utf-8"
    )
    all_candidates, regions, subwindow_records, acquisition = [], [], {}, []
    input_manifest = []
    for path in sorted((ROOT / "data/raw").rglob("*")):
        if path.is_file() and path.suffix in {
            ".hgt",
            ".swb",
            ".num",
            ".img",
            ".tiff",
            ".json",
        }:
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            input_manifest.append(
                {
                    "path": path.relative_to(ROOT).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": digest,
                }
            )
    input_hash = canonical_hash(input_manifest)
    implementation_hash = canonical_hash(
        {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in [
                "scripts/build_discovery.py",
                "scripts/measure_regions.py",
                "src/terrain.py",
                "src/suites.py",
                "src/ranking.py",
                "src/selection.py",
            ]
        }
    )
    for definition in config["regions"]:
        available = [
            tile
            for tile in definition["tiles"]
            if (ROOT / f"data/raw/earth/nasadem/NASADEM_HGT_{tile}/{tile}.hgt").exists()
        ]
        missing = sorted(set(definition["tiles"]) - set(available))
        cache = ROOT / f"data/processed/discovery-{definition['id']}.json"
        cache_key = canonical_hash(
            {
                "definition": definition,
                "available": available,
                "protocol": frozen["protocol_hash"],
                "implementation": implementation_hash,
                "input_hash": input_hash,
            }
        )
        if (
            not fresh
            and cache.exists()
            and json.loads(cache.read_text())["cache_key"] == cache_key
        ):
            record = json.loads(cache.read_text())
            print(
                f"{definition['id']}: verified matching measurement cache", flush=True
            )
        else:
            measured, contexts, region_list, _, attempted = measure_regions(
                ROOT,
                protocol,
                {**config, "regions": [{**definition, "tiles": available}]},
                terrain_image,
            )
            projected = np.load(
                ROOT / f"data/processed/{definition['id']}-projected.npz"
            )["elevation"]
            coarse = smooth_grid(projected, 125, 1000)
            window_records = {}
            for candidate in measured:
                axis = np.arange(-39500, 40000, 1000)
                x, y = np.meshgrid(
                    axis + candidate["easting_m"], -axis + candidate["northing_m"]
                )
                coarse_context = map_coordinates(
                    coarse,
                    [
                        (config["extent_m"] / 2 - y) / 125 - 0.5,
                        (x + config["extent_m"] / 2) / 125 - 0.5,
                    ],
                    order=1,
                    mode="constant",
                    cval=np.nan,
                )
                window_records[candidate["id"]] = extract_subwindows(
                    {"500": contexts[candidate["id"]], "1000": coarse_context}
                )
            record = {
                "cache_key": cache_key,
                "candidates": measured,
                "regions": region_list,
                "subwindows": window_records,
                "attempted": attempted,
            }
            cache.write_text(json.dumps(record, allow_nan=False), encoding="utf-8")
            del contexts
        all_candidates.extend(record["candidates"])
        regions.extend(record["regions"])
        subwindow_records.update(record["subwindows"])
        acquisition.append(
            {
                "region_id": definition["id"],
                "requested_tiles": definition["tiles"],
                "acquired_tiles": available,
                "unavailable_tiles": missing,
                "valid_windows": len(record["candidates"]),
                "excluded_windows": record["attempted"] - len(record["candidates"]),
                "exclusion_rule": "Missing terrain or water causes local/context validity below .95 in any required tier",
            }
        )
    targets = deepcopy(baseline["targets"])
    target_subwindows = {}
    for target in targets:
        source = open_pds(
            ROOT
            / (
                "data/raw/mars/mola/megt44n000hb.img"
                if target["body"] == "Mars"
                else "data/raw/moon/lola/ldem_64.img"
            ),
            ROOT
            / (
                "data/raw/mars/mola/megt44n000hb.xml"
                if target["body"] == "Mars"
                else "data/raw/moon/lola/ldem_64.xml"
            ),
            "mola" if target["body"] == "Mars" else "lola",
        )
        z, _ = project_window(
            source, target["latitude"], target["longitude"], 80000, 125
        )
        _, grids = tiers(z)
        target_subwindows[target["id"]] = extract_subwindows(grids)
    runs, suites, investigations, benchmark, requirement_coverages = {}, {}, {}, [], {}
    for task in contracts["tasks"]:
        task_protocol = {
            **protocol,
            "task": task["id"],
            "task_version": task["version"],
            "weights": task["weights"],
        }
        task_runs, task_suites = {}, {}
        for target in targets:
            tid = target["id"]
            result = rank(all_candidates, target, task_protocol)
            coarse_result = rank(all_candidates, target, task_protocol, 1000)
            task_runs[tid] = {"500": result, "1000": coarse_result}
            if tid not in requirement_coverages:
                requirement_coverages[tid] = {
                    c["id"]: requirement_coverage(
                        subwindow_records[c["id"]],
                        target_subwindows[tid],
                        contracts["suite"],
                    )
                    for c in all_candidates
                }
            coverage = requirement_coverages[tid]
            if task["id"] == "terrain_diversity_sampling":
                requirement_coverages[tid] = coverage
                task_suites[tid] = select_suite(
                    result, all_candidates, coverage, contracts["suite"]
                )
                task_suites[tid]["selected_subwindows"] = {
                    cid: subwindow_records[cid]
                    for cid in task_suites[tid]["selected"]["candidate_ids"]
                }
            if task["id"] == "regional_geomorphological_mapping":
                ids, roles, matches, unfilled = freeze_shortlist(
                    result["candidates"],
                    all_candidates,
                    config["selection_rule"],
                    protocol["scenario_seed"],
                )
                investigations[tid] = {
                    "run_hash": result["run_hash"],
                    "frozen_at": config["frozen_at"],
                    "shortlist": [
                        {
                            "candidate_id": cid,
                            "role": roles[cid],
                            "matched_to": matches.get(cid),
                            "claim_level": "screened_candidate",
                            "assessment_status": "unassessed_in_v4",
                        }
                        for cid in ids
                    ],
                    "unfilled_slots": unfilled,
                }
            top = {r["id"] for r in result["candidates"][:10]}
            other = {r["id"] for r in coarse_result["candidates"][:10]}
            coarse_ranks = {r["id"]: r["rank"] for r in coarse_result["candidates"]}
            no_context = rank(
                all_candidates, target, task_protocol, weights=[*task["weights"][:3], 0]
            )
            benchmark.append(
                {
                    "task_id": task["id"],
                    "target_id": tid,
                    "original_split": target["split"],
                    "evaluation_status": "exploratory_reused_target",
                    "top10_jaccard": len(top & other) / len(top | other),
                    "rank_correlation": float(
                        spearmanr(
                            [r["rank"] for r in result["candidates"]],
                            [coarse_ranks[r["id"]] for r in result["candidates"]],
                        ).statistic
                    ),
                    "winner": result["candidates"][0]["id"],
                    "without_context_winner": no_context["candidates"][0]["id"],
                    "without_context_top10_overlap": len(
                        top & {r["id"] for r in no_context["candidates"][:10]}
                    )
                    / 10,
                    "support_matching_ablation": "Not treated as an independent source; 500m versus 1km comparison reported; unsmoothed sensitivity recorded separately",
                    "independent_relevance_labels": 0,
                }
            )
            print(
                f"{task['id']}/{tid}: ranked {len(all_candidates)} windows", flush=True
            )
        runs[task["id"]] = task_runs
        suites[task["id"]] = task_suites
    source_manifest = []
    for path in sorted((ROOT / "data/raw").rglob("*")):
        if path.is_file() and path.suffix in {".hgt", ".swb", ".num", ".img", ".tiff"}:
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            source_manifest.append(
                {
                    "path": path.relative_to(ROOT).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": digest,
                }
            )
    output = {
        **frozen,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_hash": canonical_hash(source_manifest),
        "source_manifest": source_manifest,
        "regions": regions,
        "acquisition": acquisition,
        "tasks": contracts,
        "targets": targets,
        "candidates": all_candidates,
        "runs": runs,
        "suites": suites,
        "investigations": investigations,
        "benchmark": benchmark,
        "target_subwindows": target_subwindows,
        "baseline_protocol_hash": baseline["protocol_hash"],
        "claim": "Exploratory six-region screening; every new nomination requires separately recorded corroboration and novelty review",
    }
    output["requirement_coverages"] = requirement_coverages
    output["implementation_hash"] = implementation_hash
    output["record_hash"] = canonical_hash(
        {k: v for k, v in output.items() if k != "generated_at"}
    )
    (PUBLIC / "discovery.json").write_text(
        json.dumps(output, allow_nan=False), encoding="utf-8"
    )
    view = {
        k: output[k]
        for k in (
            "protocol_hash",
            "record_hash",
            "regions",
            "acquisition",
            "tasks",
            "targets",
            "suites",
            "investigations",
            "benchmark",
            "target_subwindows",
            "claim",
        )
    }
    view["candidate_count"] = len(all_candidates)
    view["runs"] = {}
    visible_ids = set()
    for task_id, task_runs in runs.items():
        view["runs"][task_id] = {}
        for tid, target_runs in task_runs.items():
            view["runs"][task_id][tid] = {}
            for tier, result in target_runs.items():
                selected_rows = result["candidates"][:100]
                lookup = {c["id"]: c for c in all_candidates}
                for region in regions:
                    selected_rows += [
                        r
                        for r in result["candidates"]
                        if lookup[r["id"]]["region_id"] == region["id"]
                    ][:5]
                selected_rows = sorted(
                    {r["id"]: r for r in selected_rows}.values(),
                    key=lambda r: r["rank"],
                )
                visible_ids.update(r["id"] for r in selected_rows)
                view["runs"][task_id][tid][tier] = {
                    **result,
                    "candidates": selected_rows,
                    "full_candidate_count": len(result["candidates"]),
                }
    visible_ids.update(
        d["candidate_id"] for inv in investigations.values() for d in inv["shortlist"]
    )
    visible_ids.update(
        cid
        for task_suites in suites.values()
        for suite in task_suites.values()
        for cid in suite["selected"]["candidate_ids"]
    )
    view["candidates"] = [c for c in all_candidates if c["id"] in visible_ids]
    (PUBLIC / "discovery_view.json").write_text(
        json.dumps(view, allow_nan=False), encoding="utf-8"
    )
    (REPORTS / "discovery_benchmark.json").write_text(
        json.dumps(benchmark, indent=2), encoding="utf-8"
    )
    pq.write_table(
        pa.Table.from_pylist(all_candidates),
        ROOT / "data/processed/discovery_features.parquet",
        compression="zstd",
    )
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [c["footprint"]]},
                "properties": {
                    k: c[k] for k in ("id", "region_id", "latitude", "longitude")
                },
            }
            for c in all_candidates
        ],
    }
    (PUBLIC / "discovery_footprints.geojson").write_text(
        json.dumps(geojson), encoding="utf-8"
    )
    print(
        f"Built separate discovery record: {len(all_candidates)} candidates in {len(regions)} bounded regions",
        flush=True,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Recompute every descriptor from raw source bytes",
    )
    build(parser.parse_args().fresh)
