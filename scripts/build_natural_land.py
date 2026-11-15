"""A separate v5 masked, availability-filtered, context-declustered experiment."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import numpy as np
from scipy.ndimage import map_coordinates
from build_research import tiers
from src.terrain import features, smooth_grid, open_pds, project_window
from src.ranking import canonical_hash, rank
from src.masks import natural_land_mask, decluster

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "apps/web/public/research"
REPORTS = ROOT / "artifacts/reports"


def build(version="v5"):
    base = json.loads((PUBLIC / "discovery.json").read_text())
    config = json.loads((ROOT / f"configs/natural_land_{version}.json").read_text())
    if version != "v5":
        coverage = json.loads((REPORTS / "coverage_v6.json").read_text())
        if coverage["base_record_hash"] != base["record_hash"]:
            raise ValueError(
                "Coverage follow-up does not match the frozen candidate domain"
            )
        for candidate in base["candidates"]:
            candidate.update(coverage["candidate_overrides"][candidate["id"]])
    prospective = json.loads((ROOT / "configs/prospective_targets_v5.json").read_text())
    camera_path = REPORTS / "prospective_camera_v5.json"
    cameras = json.loads((REPORTS / "planetary_imagery.json").read_text()) + (
        json.loads(camera_path.read_text()) if camera_path.exists() else []
    )
    camera_by_id = {c["target_id"]: c for c in cameras}
    targets = deepcopy(base["targets"])
    mola = open_pds(
        ROOT / "data/raw/mars/mola/megt44n000hb.img",
        ROOT / "data/raw/mars/mola/megt44n000hb.xml",
        "mola",
    )
    for definition in prospective["targets"]:
        z, _ = project_window(
            mola, definition["latitude"], definition["longitude"], 80000, 125
        )
        measured, _ = tiers(z)
        targets.append(
            {
                **definition,
                "features": measured,
                "projection": f"AEQD Mars R3396000, {definition['latitude']}, {definition['longitude']}",
            }
        )
    source_manifests = [
        json.loads(
            (
                ROOT
                / f"data/raw/earth/{'human_masks' if version == 'v5' else 'human_masks_v6'}/{r['id']}/manifest.json"
            ).read_text()
        )
        for r in base["regions"]
    ]
    input_hash = canonical_hash(
        {
            "base_record_hash": base["record_hash"],
            "mask_sources": source_manifests,
            "prospective": prospective,
            "camera": cameras,
        }
    )
    protocol = {
        **base["protocol"],
        "id": config["id"],
        "parent_protocol": config["parent"],
        "natural_land_experiment": config,
    }
    experiments = {}
    for buffer_m in config["mask"]["buffers_m"]:
        candidates, exclusions, mask_summaries, lead_diagnostics = [], [], [], []
        for region in base["regions"]:
            field = np.load(ROOT / f"data/processed/{region['id']}-projected.npz")[
                "elevation"
            ]
            masks = np.load(
                ROOT
                / f"data/processed/{region['id']}-human-masks{'' if version == 'v5' else '-v6'}.npz"
            )
            natural, summary = natural_land_mask(
                masks["classes"], masks["roads"], 125, buffer_m
            )
            source_record = next(
                m for m in source_manifests if m["region_id"] == region["id"]
            )
            mask_summaries.append(
                {
                    "region_id": region["id"],
                    **summary,
                    "osm_status": source_record["osm_status"],
                }
            )
            fields = {
                str(s): smooth_grid(np.where(natural, field, np.nan), 125, s)
                for s in [500, 1000]
            }
            region_candidates = [
                c for c in base["candidates"] if c["region_id"] == region["id"]
            ]
            for candidate in region_candidates:
                measured, failures = {}, []
                for spacing in [500, 1000]:
                    axis = np.arange(-40000 + spacing / 2, 40000, spacing)
                    x, y = np.meshgrid(
                        axis + candidate["easting_m"], -axis + candidate["northing_m"]
                    )
                    window = map_coordinates(
                        fields[str(spacing)],
                        [(116000 - y) / 125 - 0.5, (x + 116000) / 125 - 0.5],
                        order=1,
                        mode="constant",
                        cval=np.nan,
                    )
                    measured[str(spacing)] = features(window, spacing)
                    if spacing == 500:
                        measured["eroded"] = features(window, spacing, erode=True)
                    if measured[str(spacing)] is None:
                        failures.append(
                            f"{spacing}m valid terrain below frozen minimum after masking and smoothing"
                        )
                image_ok = (
                    candidate["reserved_hls_valid_fraction"] >= 0.95
                    and candidate["hls_context_valid_fraction"] >= 0.95
                )
                if not image_ok:
                    failures.append(
                        "Earth clear-image availability below .95 locally or contextually"
                    )
                row = int((116000 - candidate["northing_m"]) / 125)
                col = int((116000 + candidate["easting_m"]) / 125)
                diagnostics = {
                    "candidate_id": candidate["id"],
                    "mapped_natural_local_fraction_before_smoothing": float(
                        natural[row - 80 : row + 80, col - 80 : col + 80].mean()
                    ),
                    "mapped_natural_context_fraction_before_smoothing": float(
                        natural[row - 320 : row + 320, col - 320 : col + 320].mean()
                    ),
                    "image_available": image_ok,
                    "failed_rules": failures,
                }
                if candidate["id"] in {
                    "MOJAVE-142000-046000",
                    "MOROCCO-103000-100000",
                    "NAMIB-157000-136000",
                }:
                    lead_diagnostics.append(diagnostics)
                if failures or not all(measured.values()):
                    exclusions.append(diagnostics)
                else:
                    candidates.append(
                        {
                            **candidate,
                            "features": measured,
                            "source_ids": candidate["source_ids"]
                            + [
                                "worldcover2021",
                                "osm_modification_mask"
                                if source_record["osm_status"].startswith("acquired")
                                else "osm_unavailable",
                            ],
                        }
                    )
            print(
                region["id"],
                buffer_m,
                "buffer:",
                len(candidates),
                "cumulative eligible",
                flush=True,
            )
        results, investigations = {}, {}
        for target in targets:
            tid = target["id"]
            task_protocol = {
                **protocol,
                "human_buffer_m": buffer_m,
                "eligibility": "terrain + clear Earth image before selection",
            }
            result = rank(candidates, target, task_protocol)
            declustered = decluster(result["candidates"], candidates)
            camera = camera_by_id.get(tid)
            camera_ok = bool(camera and camera.get("valid_alpha_fraction", 0) >= 0.95)
            rows = [
                r for r in declustered["selected"] if r["passes_provisional_threshold"]
            ]
            nomination, control, reason = None, None, None
            if not camera_ok:
                reason = "Planetary 80km camera coverage is unavailable or below .95; no corroboration-ready pair frozen"
            elif not rows:
                reason = "No natural-mask/clear-image candidate passes the frozen terrain cutoff"
            else:
                nomination = rows[0]["id"]
                lookup = {c["id"]: c for c in candidates}
                feature = lookup[nomination]["features"]["500"]
                possible = [
                    r
                    for r in rows[1:]
                    if lookup[r["id"]]["region_id"] == lookup[nomination]["region_id"]
                    and abs(
                        lookup[r["id"]]["features"]["500"]["slope_median_deg"]
                        - feature["slope_median_deg"]
                    )
                    <= config["controls"]["median_slope_tolerance_deg"]
                    and abs(
                        lookup[r["id"]]["features"]["500"]["relief_m"]
                        - feature["relief_m"]
                    )
                    <= config["controls"]["relief_tolerance_m"]
                ]
                if possible:
                    rng = np.random.default_rng(config["controls"]["seed"])
                    control = possible[int(rng.integers(len(possible)))]["id"]
                else:
                    reason = "No lower-ranked non-overlapping same-region control meets the frozen slope/relief tolerances; no rank-band or separation rule relaxed"
            results[tid] = {
                "ranking": result,
                "declustered": declustered,
                "planetary_image_available": camera_ok,
            }
            investigations[tid] = {
                "target_id": tid,
                "nomination": nomination,
                "control": control,
                "unfilled_reason": reason,
                "frozen_at": config["frozen_at"],
                "state": "frozen_pair" if nomination and control else "incomplete_pair",
                "assessment_status": "not_independently_reviewed",
                "claim_level": "screened_candidate",
            }
        experiments[str(buffer_m)] = {
            "candidates": candidates,
            "eligible_count": len(candidates),
            "exclusions": exclusions,
            "mask_summaries": mask_summaries,
            "old_lead_diagnostics": lead_diagnostics,
            "results": results,
            "investigations": investigations,
        }
    # Absolute loss is unchanged by adding unrelated candidates when features/task are fixed.
    previous = json.loads((PUBLIC / "bundle.json").read_text())
    pool_sensitivity = []
    for tid in ["jezero", "syrtis"]:
        cid = previous["rankings"][tid]["candidates"][0]["id"]
        old = next(r for r in previous["rankings"][tid]["candidates"] if r["id"] == cid)
        new = next(
            r
            for r in base["runs"]["regional_geomorphological_mapping"][tid]["500"][
                "candidates"
            ]
            if r["id"] == cid
        )
        pool_sensitivity.append(
            {
                "target_id": tid,
                "candidate_id": cid,
                "old_rank": old["rank"],
                "expanded_rank": new["rank"],
                "old_robust_loss": old["robust_loss"],
                "expanded_robust_loss": new["robust_loss"],
                "interpretation": "Relative rank can worsen when better candidates enter; identical absolute loss is not evidence that a physical association became an artifact. Spatial and support sensitivity remain separate questions.",
            }
        )
    output = {
        "protocol": protocol,
        "protocol_hash": canonical_hash(protocol),
        "input_hash": input_hash,
        "targets": targets,
        "regions": base["regions"],
        "experiments": experiments,
        "pool_sensitivity": pool_sensitivity,
        "claim": "Mapped-natural-land sensitivity and prospective cross-scale methods experiment; no new analogue or operational mapping utility established",
        "source_limits": source_manifests,
    }
    if version != "v5":
        output["coverage_record_hash"] = coverage["record_hash"]
        output["followup_status"] = (
            "Exploratory reuse of inspected targets, no confirmatory or discovery claim"
        )
    output["record_hash"] = canonical_hash(output)
    output["generated_at"] = datetime.now(timezone.utc).isoformat()
    (PUBLIC / f"natural_land_{version}.json").write_text(
        json.dumps(output, allow_nan=False), encoding="utf-8"
    )
    (REPORTS / f"natural_land_{version}_summary.json").write_text(
        json.dumps(
            {
                "protocol_hash": output["protocol_hash"],
                "record_hash": output["record_hash"],
                "eligible_counts": {
                    k: v["eligible_count"] for k, v in experiments.items()
                },
                "pairs": {k: v["investigations"] for k, v in experiments.items()},
                "old_lead_diagnostics": {
                    k: v["old_lead_diagnostics"] for k, v in experiments.items()
                },
                "pool_sensitivity": pool_sensitivity,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        f"Published {version} masks and frozen retrieval; no claim promotion",
        flush=True,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--version", choices=["v5", "v6"], default="v5")
    build(parser.parse_args().version)
