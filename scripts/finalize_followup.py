"""Join separately measured follow-up evidence without promoting discovery claims."""

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

from src.ranking import canonical_hash

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "apps/web/public/research"
REPORTS = ROOT / "artifacts/reports"


def finalize():
    natural = json.loads((PUBLIC / "natural_land_v6.json").read_text())
    coverage = json.loads((REPORTS / "coverage_v6.json").read_text())
    fine = json.loads((REPORTS / "prospective_validation_v6.json").read_text())
    frame = json.loads((PUBLIC / "global_frame_v6.json").read_text())
    manifest = json.loads((PUBLIC / "global_nasadem_manifest_v6.json").read_text())
    terrain_stem = (
        "global_terrain_v8"
        if (PUBLIC / "global_terrain_v8.json").exists()
        else "global_terrain_v7"
    )
    pilot = json.loads((PUBLIC / f"{terrain_stem}.json").read_text())
    geology = json.loads((PUBLIC / "geology_v6.json").read_text())
    spectra = json.loads((PUBLIC / "puga_control_v6.json").read_text())
    if fine["natural_land_record_hash"] != natural["record_hash"]:
        raise ValueError("Finer observations do not match the frozen follow-up ranking")
    if natural["coverage_record_hash"] != coverage["record_hash"]:
        raise ValueError("Coverage and follow-up records disagree")
    buffers, pairs = [], []
    image_count = sum(
        row["reserved_hls_valid_fraction"] >= 0.95
        and row["hls_context_valid_fraction"] >= 0.95
        for row in coverage["candidate_overrides"].values()
    )
    for buffer, experiment in natural["experiments"].items():
        terrain_only = experiment["eligible_count"] + sum(
            all("valid terrain" not in reason for reason in row["failed_rules"])
            for row in experiment["exclusions"]
        )
        buffers.append(
            {
                "buffer_m": int(buffer),
                "eligible_count": experiment["eligible_count"],
                "terrain_only_count": terrain_only,
                "clear_image_count": image_count,
                "complete_pairs": sum(
                    p["state"] == "frozen_pair"
                    for tid, p in experiment["investigations"].items()
                    if tid.startswith("prospective")
                ),
            }
        )
        pairs.extend(
            {**p, "buffer_m": int(buffer)}
            for tid, p in experiment["investigations"].items()
            if tid.startswith("prospective")
        )
    stats = spectra["summary"]
    output = {
        "id": "mimesis-research-followup-v6",
        "claim": "New observations test the earlier nominations. No new analogue discovery or operational mapping benefit is established; global samples and known controls remain separately labelled.",
        "followup": {
            "buffers": buffers,
            "regions": [
                {
                    k: r[k]
                    for k in [
                        "region_id",
                        "scene_count",
                        "clear_context_fraction",
                        "osm_status",
                    ]
                }
                for r in coverage["regions"]
            ],
            "pairs": pairs,
            "fine_complete_pairs": fine["primary_complete_target_pairs"],
        },
        "global": {
            "terrain_stem": terrain_stem,
            "count": frame["selection"]["accepted_count"],
            "requested_count": frame["selection"]["requested_count"],
            "missing_tile_count": sum(
                not all(
                    (
                        ROOT
                        / "data/raw/earth/nasadem"
                        / f"NASADEM_HGT_{t['tile']}"
                        / name
                    ).is_file()
                    and (
                        ROOT
                        / "data/raw/earth/nasadem"
                        / f"NASADEM_HGT_{t['tile']}"
                        / name
                    )
                    .stat()
                    .st_size
                    == size
                    for name, size in t["expected_members"].items()
                )
                for t in manifest["tiles"]
            ),
            "pilot": {
                "frozen_count": pilot["summary"]["frozen_block_count"],
                "measured_count": pilot["summary"]["measured_block_count"],
                "excluded_count": pilot["summary"]["excluded_block_count"],
                "target_count": pilot["summary"]["target_count"],
                "passing_targets": pilot["summary"][
                    "targets_with_descriptive_cutoff_pass"
                ],
                "leaders": [
                    {
                        "target_id": r["target_id"],
                        "candidate_id": r["leader"]["id"],
                        "robust_loss": r["leader"]["robust_loss"],
                        "state": r["cutoff_state"],
                    }
                    for r in pilot["target_summaries"]
                ],
                "limitations": pilot["limitations"],
            },
            "blocks": [
                {
                    "id": b["id"],
                    "latitude": b["latitude"],
                    "longitude": b["longitude"],
                    "stratum": b["stratum"],
                    "ai_ratio": b["center_climate"]["ai_ratio"],
                }
                for b in frame["blocks"]
            ],
            "limitations": frame["restrictions"],
        },
        "geology": {
            "coverage_fraction": geology["jezero"]["map_coverage_fraction"],
            "unit_class_count": geology["jezero"]["unit_class_count"],
            "contact_length_km": geology["jezero"]["contacts"]["total_length_km"],
            "certainty": [
                {"name": name, "length_km": values["length_km"]}
                for name, values in geology["jezero"]["contacts"][
                    "by_certainty"
                ].items()
            ],
            "limits": [
                "SIM3464 is a 1:75,000 published geological interpretation, not an independent blind annotation.",
                "Source metadata reports 100-200 m random offsets relative to the July 2020 controlled CTX mosaic. Geological contact uncertainty and registration error are different quantities.",
                "All six prospective windows are outside this map; missing coverage is not an absence of geological contacts.",
            ],
        },
        "spectroscopy": {
            "asset_count": stats["native_file_count"],
            "pair_count": stats["matched_pair_count"],
            "mismatch_count": stats["mismatch_pair_count"],
            "nearest_sam_count": stats["same_sample_nearest_by_sam_count"],
            "nearest_continuum_count": stats[
                "same_sample_nearest_by_continuum_rmse_count"
            ],
            "matched_sam": stats["matched"]["spectral_angle_radians"]["median"],
            "mismatch_sam": stats["mismatch"]["spectral_angle_radians"]["median"],
            "pairs": [
                {
                    "sample_id": p["sample_id"],
                    "sam": p["spectral_angle_radians"],
                    "continuum_rmse": p["continuum_removed_rmse"],
                    "sam_rank": p["ranks"]["spectral_angle_radians"]["best_rank"],
                }
                for p in spectra["matched_pairs"]
            ],
            "limits": spectra["limitations"],
        },
        "judging": [
            {
                "criterion": "Impact",
                "evidence": "Inspectable site-screening decisions, explicit exclusions and exported source records.",
                "remaining": "Measured human or algorithmic mapping-rehearsal benefit and field validation.",
            },
            {
                "criterion": "Creativity",
                "evidence": "An eligibility follow-up, frozen global sample and known-control specificity checks.",
                "remaining": "A defensible new association or independently benchmarked methodological improvement.",
            },
            {
                "criterion": "Validity",
                "evidence": "Body-aware geometry, fixed source/scale contracts, real masks and abstention.",
                "remaining": "Independent task labels, suitable contacts for fresh targets, and instrument/source uncertainty.",
            },
            {
                "criterion": "Relevance",
                "evidence": "NASA Earth and planetary observations drive a named analogue-screening task.",
                "remaining": "Corroborated geological/process relevance for a new candidate.",
            },
            {
                "criterion": "Presentation",
                "evidence": "Source-backed maps, case records, reports and accessible offline workflows.",
                "remaining": "Actual2026 submission rules, verified-format demonstration and public submission.",
            },
        ],
        "lineage": {
            "natural_land": natural["record_hash"],
            "coverage": coverage["record_hash"],
            "frame": frame["frame_sha256"],
            "global_pilot": pilot["record_hash"],
            "geology": canonical_hash(geology),
            "spectroscopy": canonical_hash(spectra),
            "fine": canonical_hash(fine),
        },
    }
    output["record_hash"] = canonical_hash(output)
    output["generated_at"] = datetime.now(timezone.utc).isoformat()
    (PUBLIC / "research_v6.json").write_text(
        json.dumps(output, indent=2, allow_nan=False), encoding="utf-8"
    )
    for name in ["prospective_validation_v6.json", "coverage_v6.json"]:
        shutil.copy2(REPORTS / name, PUBLIC / name)
    shutil.copy2(
        ROOT / "data/derived/puga_control_v6/puga_control_v6.md",
        PUBLIC / "puga_control_v6_report.md",
    )
    shutil.copy2(
        ROOT / "data/derived/puga_control_v6/puga_sam_matrix.png",
        PUBLIC / "puga_sam_matrix.png",
    )
    shutil.copy2(ROOT / "PLAN.md", PUBLIC / "PLAN.md")
    lines = [
        "# MIMESIS research follow-up v6",
        "",
        output["claim"],
        "",
        "## Eligibility after additional observations",
        "",
        "The original 8,507-window domain, cutoff, support and matching tolerances remain fixed. New HLS scenes and available real OSM extracts enter a separate version. Targets and earlier fine outcomes have already been inspected; this is exploratory.",
        "",
        "| Buffer | Image only | Masked terrain only | Combined | Prospective frozen pairs |",
        "|---|---:|---:|---:|---:|",
    ]
    lines += [
        f"|{b['buffer_m']}m|{b['clear_image_count']}|{b['terrain_only_count']}|{b['eligible_count']}|{b['complete_pairs']}|"
        for b in buffers
    ]
    lines += [
        "",
        f"Usable finer-observation pairs: {fine['primary_complete_target_pairs']}. Every missing nomination/control and failed finer crop is retained. No human rehearsal performance has been measured.",
        "",
        "## Presampled global terrain comparison",
        "",
        f"The corrected supplied climate products define {frame['selection']['accepted_count']} non-overlapping contexts, 50 per hot/cold desert stratum. The full native elevation manifest has {frame['acquisition_manifest']['unique_tile_count']} tiles. Source coverage, geological relevance and novelty are separate gates; the terrain experiment reports its measured denominator and exclusions without a discovery-accuracy or global-rarity claim.",
        "",
        "## Geological reference",
        "",
        f"The real SIM3464 map covers the Jezero local window and contains {geology['jezero']['unit_class_count']} unit classes and {geology['jezero']['contacts']['total_length_km']:.3f}km of clipped contacts. Certain and approximate types remain distinct. The six prospective windows lie outside its extent. Registration offsets and geological uncertainty prevent treating all map lines as exact truth.",
        "",
        "## Known spectroscopy control",
        "",
        f"{stats['native_file_count']} original Puga files produce {stats['matched_pair_count']} same-ID and {stats['mismatch_pair_count']} different-ID comparisons. Same specimen is nearest in {stats['same_sample_nearest_by_sam_count']}/10 by spectral angle and {stats['same_sample_nearest_by_continuum_rmse_count']}/10 by continuum RMSE. Different samples can share minerals; these are descriptive controls, not independent identification accuracy. Puga is an established analogue, not a discovery.",
        "",
        "## Geological and observational limitations",
        "",
        "Appropriate fine contacts for prospective targets, independent blind task annotations, fieldwork, complete global land-use and imagery gates, a verified orbital spectral pair, calibrated thermal/polar observations and actual event submission requirements remain distinct gaps. Supplied global climate raw data are not redistributed while source licensing statements conflict. Exact PEDR shot matching has not been performed.",
        "",
        "## Reproduction",
        "",
        "Run prepare_followup.py; build_natural_land.py --version v6; validate_stereo_transfer.py --version v6; build_global_frame.py; measure_global_pilot.py --config configs/global_terrain_v8.json; characterize_geology.py; characterize_puga.py; then finalize_followup.py. Raw acquisition precedes these steps. V3 through V5 records are preserved. Source and code/config identities accompany component JSON records.",
        "",
        f"Joined record SHA256: `{output['record_hash']}`.",
    ]
    heading = lines.index("## Geological reference")
    global_results = [
        f"Measured {pilot['summary']['measured_block_count']} of {pilot['summary']['frozen_block_count']} frozen contexts; {pilot['summary']['excluded_block_count']} are excluded. Terrain matches pass no completed global imagery, anthropogenic, geological or task-utility gate.",
        "",
        "| Planetary target | Global leader | Robust loss | Passing / measured |",
        "|---|---|---:|---:|",
    ]
    for case in pilot["target_summaries"]:
        leader = case["leader"]
        loss = f"{leader['robust_loss']:.6f}" if leader else "unavailable"
        global_results.append(
            f"| {case['name']} | {leader['id'] if leader else 'none'} | {loss} | {case['passing_count']} / {case['eligible_count']} |"
        )
    global_results += [
        "",
        "Scuderi and Mason (2021), Gobi Desert deltas as analogs for Jezero crater, already establishes a regional Gobi/Jezero comparison: https://www.hou.usra.edu/meetings/terrestrialanalogs2021/pdf/8083.pdf. Exact sampled-footprint overlap is unresolved. Absence from this bounded audit would not establish novelty elsewhere.",
        "",
    ]
    lines[heading:heading] = global_results
    report = "\n".join(lines) + "\n"
    (REPORTS / "research_v6_report.md").write_text(report, encoding="utf-8")
    (PUBLIC / "research_v6_report.md").write_text(report, encoding="utf-8")
    print("Published joined research follow-up", output["record_hash"], flush=True)


if __name__ == "__main__":
    finalize()
