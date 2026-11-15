"""Publish the complete v5 feasibility result, including rejected hypotheses."""

import json
from pathlib import Path
import shutil
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from src.masks import natural_land_mask
from src.ranking import canonical_hash

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "apps/web/public/research"
REPORTS = ROOT / "artifacts/reports"


def finalize():
    data = json.loads((PUBLIC / "natural_land_v5.json").read_text())
    base = json.loads((PUBLIC / "discovery.json").read_text())
    summary = json.loads((REPORTS / "natural_land_v5_summary.json").read_text())
    validation = json.loads((REPORTS / "prospective_validation_v5.json").read_text())
    support = json.loads((REPORTS / "mola_support_v5.json").read_text())
    cameras = json.loads((REPORTS / "prospective_camera_v5.json").read_text())
    if validation["natural_land_record_hash"] != data["record_hash"]:
        raise ValueError("Fine validation does not match the published masked ranking")
    targets = [t for t in data["targets"] if t["id"].startswith("prospective")]
    camera_by_id = {c["target_id"]: c for c in cameras}
    summary["targets"] = [
        {
            "id": t["id"],
            "latitude": t["latitude"],
            "longitude": t["longitude"],
            "stereo_valid_fraction": t["stereo_valid_fraction"],
            "camera_valid_fraction": camera_by_id.get(t["id"], {}).get(
                "valid_alpha_fraction", 0
            ),
            "stereo_source_id": t["stereo_source_id"],
            "stereo_url": t["stereo_url"],
            "image": camera_by_id.get(t["id"], {}).get("image"),
        }
        for t in targets
    ]
    summary["fine_results"] = []
    for row in validation["results"]:
        for role, value in row["comparisons"].items():
            summary["fine_results"].append(
                {
                    "target_id": row["target_id"],
                    "buffer_m": row["buffer_m"],
                    "role": role,
                    "candidate_id": value["candidate_id"],
                    "state": value["distance"]["state"],
                    "joint_wasserstein": value["distance"]["joint_wasserstein"],
                    "hypsometric_difference": value["distance"][
                        "hypsometric_difference"
                    ],
                    "earth_valid_fraction": value["measurements"]["valid_fraction"],
                    "planetary_valid_fraction": row["planetary"]["valid_fraction"],
                }
            )
    summary["primary_complete_target_pairs"] = validation[
        "primary_complete_target_pairs"
    ]
    summary["sign_test"] = validation["sign_test"]
    summary["mola_support"] = support["results"]
    summary["mola_support_limit"] = support["limitation"]
    summary["source_limits"] = [
        {
            "region_id": r["region_id"],
            "osm_status": r["osm_status"],
            "limitation": r["limitation"],
        }
        for r in data["source_limits"]
    ]
    summary["attrition"] = {}
    image_count = sum(
        c["reserved_hls_valid_fraction"] >= 0.95
        and c["hls_context_valid_fraction"] >= 0.95
        for c in base["candidates"]
    )
    for buffer, experiment in data["experiments"].items():
        terrain_only = experiment["eligible_count"] + sum(
            all("valid terrain" not in reason for reason in row["failed_rules"])
            for row in experiment["exclusions"]
        )
        summary["attrition"][buffer] = {
            "baseline_terrain_windows": len(base["candidates"]),
            "clear_image_only": image_count,
            "masked_terrain_only": terrain_only,
            "combined_eligible": experiment["eligible_count"],
        }
    lookup = {c["id"]: c for c in base["candidates"]}
    leads = ["MOJAVE-142000-046000", "MOROCCO-103000-100000", "NAMIB-157000-136000"]
    fig, axes = plt.subplots(2, 3, figsize=(15, 10), layout="constrained")
    for col, cid in enumerate(leads):
        candidate = lookup[cid]
        imagery = np.load(ROOT / f"data/processed/{candidate['region_id']}-imagery.npz")
        masks = np.load(
            ROOT / f"data/processed/{candidate['region_id']}-human-masks.npz"
        )
        row = int((116000 - candidate["northing_m"]) / 125)
        column = int((116000 + candidate["easting_m"]) / 125)
        window = (slice(row - 320, row + 320), slice(column - 320, column + 320))
        for index, buffer in enumerate([500, 1000]):
            natural, _ = natural_land_mask(
                masks["classes"], masks["roads"], 125, buffer
            )
            axes[index, col].imshow(imagery["rgb"][window], extent=(-40, 40, -40, 40))
            overlay = np.zeros((640, 640, 4))
            overlay[..., 0] = 0.8
            overlay[..., 3] = (~natural[window]) * 0.5
            axes[index, col].imshow(overlay, extent=(-40, 40, -40, 40))
            axes[index, col].plot(
                [-10, 10, 10, -10, -10],
                [-10, -10, 10, 10, -10],
                color="white",
                linewidth=1,
            )
            axes[index, col].set_title(
                f"{cid}\n{buffer}m modification buffer", fontsize=10
            )
            axes[index, col].set_xlabel("Local east, km")
            axes[index, col].set_ylabel("Local north, km")
    fig.suptitle(
        "WorldCover-based mask sensitivity: red is excluded, not verified human disturbance"
    )
    image = "v5-mask-diagnostics.png"
    fig.savefig(ROOT / "artifacts/figures" / image, dpi=130)
    plt.close(fig)
    shutil.copy2(ROOT / "artifacts/figures" / image, PUBLIC / image)
    summary["mask_image"] = image
    summary["claim"] = (
        "All three earlier leads fail the declared mapped-land coverage sensitivity. No new analogue discovery or mapping-utility superiority is established."
    )
    summary["limits"] = [
        "WorldCover crop/built-up classification is fallible and dated2021; NASADEM's SRTM epoch is2000. These masks do not establish a causal effect of agriculture on historical DEM heights.",
        "OSM Overpass endpoints were unavailable during acquisition. Road/industrial geometry completeness is unknown; a zero cached road mask is not interpreted as no roads.",
        "The image prefilter changes the v5 population. Its failures do not rewrite the frozen v4 investigation.",
        "No control meets the frozen same-region, nonoverlap and matching constraints. Zero complete target pairs means no paired p-value or superiority inference.",
        "SIM3292 is1:20million, unsuitable for200m contact validation. Fine contact references and independent blinded task judgments remain unavailable.",
        "Copernicus DSM may include auxiliary SRTM fill; CTX stereo is MOLA-aligned. Additional observations are not fully independent truth.",
    ]
    summary["evidence_hash"] = canonical_hash(
        {"summary": summary, "validation": validation, "support": support}
    )
    (PUBLIC / "validation_v5_view.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    for name in [
        "prospective_validation_v5.json",
        "mola_support_v5.json",
        "natural_land_v5_summary.json",
    ]:
        shutil.copy2(REPORTS / name, PUBLIC / name)
    lines = [
        "# MIMESIS v5: testing masked-land feasibility and prospective transfer",
        "",
        summary["claim"],
        "",
        f"Protocol `{summary['protocol_hash']}`; masked record `{data['record_hash']}`; joined evidence `{summary['evidence_hash']}`.",
        "",
        "## What changed after the supplied model critique",
        "",
        "This is a new experiment, not a replacement success for v4. Real WorldCover2021 crop/built-up classes were aggregated conservatively, buffered500m or1000m, and applied before smoothing and derivatives. Unknown classification coverage remains invalid. Clear Earth imagery is required before selection. Retrieval is greedily declustered at non-overlapping80km contexts with complete suppression logs. Six new Martian stereo targets were selected by frozen metadata/geometry/coverage rules before masked Earth ranking.",
        "",
        "## Eligibility, without confusing causes",
        "",
        "| Buffer | Base windows | Clear imagery only | Masked terrain only | Combined |",
        "|---|---:|---:|---:|---:|",
    ]
    for buffer, a in summary["attrition"].items():
        lines.append(
            f"| {buffer}m | {a['baseline_terrain_windows']} | {a['clear_image_only']} | {a['masked_terrain_only']} | {a['combined_eligible']} |"
        )
    lines += [
        "",
        "The combined attrition is not attributed solely to farming: source validity, mask dilation, smoothing and pre-existing image gaps contribute. All three earlier featured leads independently fail masked terrain validity while their Earth images pass. The1000m policy leaves only one eligible window; the declared matched-control design is infeasible in this bounded population. This does not establish that no useful natural analogue exists elsewhere.",
        "",
        "| Earlier lead |500m local/context mapped fraction |1000m local/context mapped fraction |",
        "|---|---|---|",
    ]
    for cid in leads:
        a = next(
            r
            for r in summary["old_lead_diagnostics"]["500"]
            if r["candidate_id"] == cid
        )
        b = next(
            r
            for r in summary["old_lead_diagnostics"]["1000"]
            if r["candidate_id"] == cid
        )
        lines.append(
            f"| {cid} | {a['mapped_natural_local_fraction_before_smoothing']:.3f} / {a['mapped_natural_context_fraction_before_smoothing']:.3f} | {b['mapped_natural_local_fraction_before_smoothing']:.3f} / {b['mapped_natural_context_fraction_before_smoothing']:.3f} |"
        )
    lines += [
        "",
        "These are mapped unflagged fractions before smoothing, not verified natural-area fractions. Historical acquisition mismatch and classification errors prevent asserting that agriculture caused the original slope matches.",
        "",
        "## Prospective stereo test",
        "",
        "Six fresh AOIs were frozen; one earlier catalogue candidate was rejected for inadequate coverage by the preset rule. They remain quality-selected cases from the retained query, not random global Mars samples. One retained AOI fails the80km camera gate even though its local DTM is usable; it is not swapped out.",
        "",
        "| AOI | Latitude | Longitude | Local stereo validity |80km camera validity |",
        "|---|---:|---:|---:|---:|",
    ]
    lines += [
        f"| {t['id']} | {t['latitude']:.5f} | {t['longitude']:.5f} | {t['stereo_valid_fraction']:.3f} | {t['camera_valid_fraction']:.3f} |"
        for t in summary["targets"]
    ]
    lines += [
        "",
        "Actual Copernicus GLO-30 DSM clips were acquired for nominated Earth windows and compared with the independently sensed CTX stereo surfaces at100m analysis spacing. The fixed joint slope/Laplacian-curvature Wasserstein metric and hypsometric integral are descriptive surrogate diagnostics. Some pairs fail finer validity despite passing coarser screening. No missing control is synthesized, substituted or selected after viewing fine outcomes. There are zero complete frozen nomination/control target pairs, so both paired significance outputs remain null and operational mapping utility is unmeasured.",
        "",
        "## Actual MOLA source support",
        "",
        "The matching native128ppd observation-count image was acquired and label/size checked. Zero-count bins reveal interpolation exposure. Native binned counts do not give actual PEDR shot positions or recreate the MEGDR interpolation kernel, so the project does not claim exact track-matched cross-body resolution.",
        "",
        "| Mars AOI | Local zero-count fraction | Context zero-count fraction |",
        "|---|---:|---:|",
    ]
    lines += [
        f"| {r['target_id']} | {r['local_zero_count_fraction']:.3f} | {r['context_zero_count_fraction']:.3f} |"
        for r in support["results"]
    ]
    lines += [
        "",
        "## Corrected interpretation and remaining evidence",
        "",
        "The unchanged Namib absolute discrepancy alongside a rank1→25 shift demonstrates pool-composition dependence of relative ranks. It does not prove that the landform association became an artifact. Separately measured support ablation and morphology counterevidence remain relevant. Five positive target differences out of six would give an exact sign-test p=.109375; a significance threshold cannot be promised from the win count.",
        "",
        "SIM3292's1:20million geologic context is not200m line truth. Fine contact evaluation requires suitable reference scale, positional accuracy, consistent body-specific metric coordinates and independently authored contacts. No expert or field validation is implied by the supplied Gemini critique.",
        "",
        "The working deliverable includes frozen records, exclusion reasons, source limits, controls that may remain unfilled, prospective source assets, quantitative diagnostics, tests and a complete API/UI evidence path. New analogue discovery remains unestablished. A larger predeclared naturally unflagged/observable Earth domain, appropriate reference maps and independently blinded judgments are needed before a new operational analogue association can be justified.",
        "",
        "## Sources",
        "",
        "- [ESA WorldCover data and validation](https://esa-worldcover.org/en/data-access),2021v200 classification and its documented errors.",
        "- [USGS CTX stereo processing](https://stac.astrogeology.usgs.gov/docs/data/mars/ctxdtms/), stereo observations and MOLA alignment.",
        "- [Copernicus DEM](https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM), DSM/reference/auxiliary-fill terms.",
        "- [MOLA MEGDR archive](https://pds-geosciences.wustl.edu/missions/mgs/megdr.html), topography and observation counts.",
        "- [SIM3292](https://pubs.usgs.gov/sim/3292/), regional scale and mapping context.",
        "",
        "Run `build_natural_land.py`, `validate_stereo_transfer.py`, `diagnose_mola_support.py`, then `finalize_natural_land.py` after source acquisition. All original v3/v4 records remain separate.",
    ]
    report = "\n".join(lines) + "\n"
    (REPORTS / "natural_land_v5_report.md").write_text(report, encoding="utf-8")
    (PUBLIC / "natural_land_v5_report.md").write_text(report, encoding="utf-8")
    print("Published complete v5 feasibility report and lightweight UI record")


if __name__ == "__main__":
    finalize()
