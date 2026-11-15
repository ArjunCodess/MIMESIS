"""Publish the completed, explicitly model-assisted remote-evidence investigation."""

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import json
import shutil
import numpy as np
from pyproj import Geod
from src.evidence import assess_packets
from src.ranking import canonical_hash

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "apps/web/public/research"
REPORTS = ROOT / "artifacts/reports"


def finalize():
    bundle = json.loads((PUBLIC / "bundle.json").read_text())
    rubric = json.loads((ROOT / "configs/corroboration_rubric.json").read_text())
    observations = json.loads((ROOT / "configs/visual_assessments.json").read_text())
    imagery = json.loads((REPORTS / "planetary_imagery.json").read_text())
    packets = json.loads((REPORTS / "evidence_packets.json").read_text())
    audit_path = ROOT / "configs/novelty_audit.json"
    novelty = (
        json.loads(audit_path.read_text())
        if audit_path.exists()
        else {"status": "pending", "candidates": []}
    )
    investigations, counts = assess_packets(
        bundle, packets, imagery, rubric, observations, novelty
    )
    bundle.update(
        {
            "investigations": investigations,
            "planetary_imagery": imagery,
            "corroboration_rubric": rubric,
            "novelty_audit": novelty,
            "assessment_summary": counts,
            "claim": "Two-region terrain screening with source-linked, model-assisted imagery assessment; novelty and independent scientific validation are not established",
        }
    )
    if not any(source["id"] == "ctx_camera" for source in bundle["sources"]):
        bundle["sources"].extend(
            [
                {
                    "id": "ctx_camera",
                    "name": "MRO CTX beta camera mosaic",
                    "body": "Mars",
                    "url": "https://trek.nasa.gov/tiles/Mars/EQ/CTX_beta01_uncontrolled_5m_Caltech/1.0.0/WMTSCapabilities.xml",
                    "role": "separate_image_assessment",
                    "units": "display intensity; no radiometric cross-body loss",
                    "encoding": "WMTS RGBA PNG, native tiles and checksums retained",
                    "nominal_spacing": "about 81 m at the equator for cached zoom 8; output 100 m",
                    "lineage": "MRO CTX optical acquisition, uncontrolled beta mosaic; geometric independence and co-registration accuracy not established",
                    "rights": "NASA/JPL-Caltech/MSSS/Murray Lab; capability points to ArcGIS tile service",
                },
                {
                    "id": "wac_camera",
                    "name": "LRO LROC WAC camera mosaic",
                    "body": "Moon",
                    "url": "https://data.lroc.im-ldi.com/lroc/view_rdr/WAC_GLOBAL/",
                    "role": "separate_image_assessment",
                    "units": "display intensity; no radiometric cross-body loss",
                    "encoding": "WMTS JPEG source tiles; projected RGBA PNG",
                    "nominal_spacing": "about 167 m at the equator for cached zoom 7; output 100 m is staging",
                    "lineage": "Separate WAC optical acquisition; non-polar orthorectification uses GLD100 and shares LOLA/GRAIL ephemeris lineage; no polar crop acquired",
                    "rights": "NASA/GSFC/Arizona State University LROC",
                },
            ]
        )
    next(source for source in bundle["sources"] if source["id"] == "hls")["lineage"] = (
        "Ten separate Landsat acquisitions, quality-masked and inspected for the frozen model-assisted landform rubric; excluded from terrain scores"
    )
    if bundle.get("regions"):
        bundle["earth"] = {
            **bundle["regions"][0],
            "name": "Atacama and Namib bounded search",
            "valid_windows": len(bundle["candidates"]),
            "attempted_windows": sum(r["attempted_windows"] for r in bundle["regions"]),
        }
    if bundle.get("regions"):
        fractions = {
            region["id"]: float(
                np.load(ROOT / f"data/processed/{region['id']}-imagery.npz")[
                    "valid"
                ].mean()
            )
            for region in bundle["regions"]
        }
        bundle["reserved_imagery"]["valid_projected_grid_fraction"] = float(
            np.mean(list(fractions.values()))
        )
        bundle["reserved_imagery"]["region_clear_grid_fractions"] = fractions
        bundle["reserved_imagery"]["interpreted"] = True
    bundle["evidence_assessed_at"] = datetime.now(timezone.utc).isoformat()
    bundle["evidence_hash"] = canonical_hash(
        {
            "rubric": rubric,
            "observations": observations,
            "imagery": imagery,
            "packets": packets,
            "novelty": novelty,
        }
    )
    write(PUBLIC / "bundle.json", bundle)
    write(REPORTS / "investigations.json", investigations)
    write(
        REPORTS / "assessment_summary.json",
        {
            "counts": counts,
            "reviewer_status": observations["reviewer_status"],
            "rubric": rubric,
            "sampling": f"{len(packets)} retained comparisons; {36 - len(packets)} unfilled slots; not a population accuracy estimate",
        },
    )
    write(REPORTS / "novelty_audit.json", novelty)
    report(bundle)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = [
        "Provisional visual support",
        "Target/task mismatch",
        "Insufficient imagery",
        "Ambiguous morphology",
    ]
    values = [
        counts.get(key, 0)
        for key in (
            "provisional_visual_support",
            "target_task_mismatch",
            "insufficient_image_coverage",
            "ambiguous_morphology",
        )
    ]
    figure, axis = plt.subplots(figsize=(9, 4.5), layout="constrained")
    bars = axis.barh(labels, values, color=["#527d70", "#a97853", "#919b9e", "#b09c71"])
    axis.bar_label(bars, padding=5)
    axis.invert_yaxis()
    axis.set_xlim(0, max(values) + 3)
    axis.set_xlabel("Retained comparisons, not independent samples")
    unfilled = sum(len(inv["unfilled_slots"]) for inv in investigations.values())
    axis.set_title(
        f"Model-assisted image assessment: {sum(values)} retained, {unfilled} unfilled"
    )
    axis.spines[["top", "right"]].set_visible(False)
    figure.savefig(ROOT / "artifacts/figures/assessment_outcomes.png", dpi=180)
    plt.close(figure)
    for name in [
        "investigations.json",
        "assessment_summary.json",
        "novelty_audit.json",
        "evidence_packets.json",
        "planetary_imagery.json",
        "research_report.md",
    ]:
        shutil.copy2(REPORTS / name, PUBLIC / name)
    print(
        "Evidence investigation completed:",
        counts,
        "; no automatic discovery promotion",
        flush=True,
    )


def write(path, value):
    path.write_text(
        json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def report(b):
    lookup = {c["id"]: c for c in b["candidates"]}
    lead = b["rankings"]["jezero"]["candidates"][0]
    candidate = lookup[lead["id"]]
    old = json.loads((ROOT / "artifacts/archive/pilot-v1/bundle.json").read_text())
    oldrow = old["rankings"]["jezero"]["candidates"][0]
    oldcandidate = next(c for c in old["candidates"] if c["id"] == oldrow["id"])
    _, _, separation = Geod(ellps="WGS84").inv(
        candidate["longitude"],
        candidate["latitude"],
        oldcandidate["longitude"],
        oldcandidate["latitude"],
    )
    counts = b["assessment_summary"]
    total = sum(counts.values())
    missing = sum(
        len(inv.get("unfilled_slots", [])) for inv in b["investigations"].values()
    )
    lines = [
        "# MIMESIS: a two-region planetary terrain analogue investigation",
        "",
        f"Generated {b['evidence_assessed_at']}. Experiment `{b['protocol']['id']}`. Protocol SHA-256 `{b['protocol_hash']}`.",
        "",
        "## Finding",
        "",
        f"The expanded search measured {len(b['candidates']):,} overlapping 20 km Earth windows across Atacama and Namib against six Moon/Mars windows. It retained {total} context-separated comparisons, with {missing} of the 36 planned slots explicitly unfilled. Of the {total} selected comparisons, {counts.get('provisional_visual_support', 0)} met the declared visible-landform rubric in a model-assisted assessment, {counts.get('target_task_mismatch', 0)} failed the target/task pairing, {counts.get('insufficient_image_coverage', 0)} lacked sufficient separate imagery, and {counts.get('ambiguous_morphology', 0)} remained morphologically ambiguous. These counts are selected-case outcomes, not discovery accuracy.",
        "",
        f"The Jezero lead is `{candidate['id']}`, centered at {candidate['latitude']:.6f}, {candidate['longitude']:.6f}, with nominal loss {lead['nominal_loss']:.6f} and robust loss {lead['robust_loss']:.6f}. Its center is approximately {separation:.0f} m from the original pilot lead. Broader search therefore retained the same small Atacama area. This is sensitivity evidence for the nomination, not an independent replication or novelty finding.",
        "",
        "The release supports a provisional, task-specific terrain-mapping hypothesis with source-linked image observations. It establishes neither a newly discovered analogue nor independent scientific validation. The imagery assessor also implemented the ranking, the regional analogue context is already known, and exact prior footprint/task associations remain bounded by the documented literature search.",
        "",
        "## Question and experimental history",
        "",
        "Can common-grid terrain screening nominate Earth windows useful for regional floor/margin mapping rehearsal, and which nominations survive a separate-camera inspection? The v1 pilot measured one tile and 921 overlapping windows. Its full serving record, protocol and reports remain under `artifacts/archive/pilot-v1/`. The v2 expansion acquired adjacent NASADEM tiles for two regions before calculating v2 rankings. Its initial 20 km footprint separation failed the original 80 km context-separation contract. Both the v2 bundle and the original audit are archived; v3 corrects selection and matching without changing measured terrain features or weights. Since the six target cases had already been inspected in v1, their original development/held-out split is retained as provenance, not presented as untouched held-out evaluation.",
        "",
        "## Data and acquisition",
        "",
        "| Region | Bounds, west/south/east/north | Terrain tiles | Valid windows |",
        "|---|---|---:|---:|",
    ]
    for r in b["regions"]:
        lines.append(
            f"| {r['name']} | {r['bounds']} | {len(r['tiles'])} | {r['valid_windows']} |"
        )
    lines += [
        "",
        "Each region joins four complete NASADEM tiles with duplicate boundary nodes removed. Earthdata authentication was used only in acquisition commands. No token or signed credential is stored in this release. The source manifest records raw file paths, byte lengths and SHA-256 hashes, including the original interrupted files. The release archive omits the large raw rasters but retains derived observations and their provenance.",
        "",
        "Independent Earth context uses ten Landsat HLS RGB/Fmask scenes. Clear observations are unioned in the declared local metric projection; fill, cirrus, cloud, adjacency, shadow, snow/ice and water mask bits are excluded. Coverage remains incomplete in several windows despite nominally low scene cloud percentages. No missing image pixels are interpreted as geological evidence.",
        "",
        "Mars camera context is the CTX beta mosaic exposed through NASA Trek capabilities and the referenced ArcGIS tile service. Source tile URLs, checksums, validity and rejected corrupt responses are retained. Jezero, Isidis and Syrtis have usable separate-camera crops; the selected Nili service crop has no usable coverage. The CTX mosaic is uncontrolled, so absolute co-registration accuracy is unvalidated. Lunar Taurus-Littrow uses separate WAC images; non-polar orthorectification uses WAC-derived GLD100, while orbital geometry also shares ephemeris lineage with LOLA/GRAIL. No polar optical crop was acquired for Shackleton. Separate acquisition is distinguished from fully independent processing.",
        "",
        "## Terrain measurements and discrepancy",
        "",
        "Each body uses its own azimuthal equidistant projection and reference shape: WGS84 for Earth, a 3396 km sphere for MOLA and a 1737.4 km sphere for LOLA. NASADEM and MOLA are big-endian int16; LOLA is little-endian int16 scaled by 0.5 m. Absolute elevation is excluded from cross-body loss. The LOLA reference radius is not added to height.",
        "",
        "A 125 m staging grid is Gaussian-smoothed with FWHM equal to the 500 m or 1 km analysis spacing before sampling the final grid. It adds no source detail. The 20 km local window and 80 km context require at least 95% valid terrain area at both spacings. Void/water masks propagate into derivatives. NASADEM supplies local source ancestry through the retained NUM files; planetary count maps have not been acquired, so interpolated cells cannot be reliably separated.",
        "",
        "Four fixed budgets compare slope-histogram Wasserstein-1 distance, local relief/topographic position, detrended RMS/gradient anisotropy, and contextual relief/standard deviation. Budgets are 0.40/0.25/0.15/0.20. Scalar losses are squared normalized discrepancies clipped at one, using the explicit physical tolerances in the frozen protocol. Tolerances and the provisional 0.35 cutoff are engineering assumptions, not relevance calibration.",
        "",
        "Robust loss is the maximum over 35 finite sensitivity scenarios: nominal, 32 seeded weight perturbations, alternative grid spacing and mask erosion. Scenario ranks and top-ten inclusion fractions are not confidence intervals or probabilities of analogue validity. A rank is always retained as a screening result; later evidence does not change its measurements or silently promote a discovery claim.",
        "",
        "## Measured ranking results",
        "",
        "| Target | Original split, reused in v2 | Robust minimum | Top-10 grid Jaccard | Rank correlation |",
        "|---|---|---:|---:|---:|",
    ]
    for t, v in zip(b["targets"], b["benchmark"]):
        lines.append(
            f"| {t['name']} | {t['split']} | {v['robust_minimum']:.6f} | {v['top10_jaccard_500_vs_1000']:.3f} | {v['rank_spearman']:.3f} |"
        )
    lines += [
        "",
        "Both lunar cases now have terrain neighbours below the provisional cutoff. Their original pilot no-match outcome is preserved in the archive; changing the bounded Earth pool changes the answer. Full rankings and nominal/slope-only baseline winners remain available. Different winners do not prove a better scientific method without independent relevance judgments.",
        "",
        "## Separate-camera assessment",
        "",
        "The declared rubric requires a floor-like unit in/adjoining the local footprint, an organized ridge/scarp/mass-defined margin in the 80 km context, and a resolved floor-to-margin transition. Clear optical coverage must reach 95% locally and contextually. Observations are restricted to landforms visible at 500 m or coarser, despite finer display pixels. Brightness is not used as a numerical slope or mineral measurement.",
        "",
        "The same rubric was applied to every retained nomination and alternative. Selection enforces non-overlapping 80 km contexts within each region. Alternatives must be lower-ranked, share the fixed slope/relief categories, and differ by at most two percentage points in local and contextual valid-terrain coverage. Unfilled slots remain explicit. Image sheets omit numerical ranks and losses, but the assessor built the ranking and knows shortlist roles; the assessment is not independently blinded. Missing camera data, incomplete clear coverage and ambiguous landforms remain distinct from contradictions.",
        "",
        "| Target | Provisional support | Target/task mismatch | Incomplete coverage | Ambiguous |",
        "|---|---:|---:|---:|---:|",
    ]
    for t in b["targets"]:
        tally = Counter(
            d["assessment_outcome"] for d in b["investigations"][t["id"]]["shortlist"]
        )
        lines.append(
            f"| {t['name']} | {tally['provisional_visual_support']} | {tally['target_task_mismatch']} | {tally['insufficient_image_coverage']} | {tally['ambiguous_morphology']} |"
        )
    lines += [
        "",
        "The Jezero/Atacama lead visually contains a floor-like unit and organized western/southwestern margin, but its strict clear-area coverage is about 94.9 percent locally, below the frozen 95 percent gate. It therefore remains unassessable under this rubric despite promising morphology. The threshold is not relaxed after inspection. Roads and rectilinear industrial surfaces are counterevidence against treating the footprint as an undisturbed natural field site. Some candidate comparisons meet broad mapping requirements while visibly differing in drainage, impact or flow-like organization; no shared formation process is inferred.",
        "",
        "The selected Isidis crop shows a plain without the regional floor/margin transition required by this rubric. This is a target/task mismatch, not a blanket rejection of Isidis for a differently declared plain-mapping task. Nili and Shackleton lack usable acquired camera evidence. The assessable Taurus-Littrow Earth alternative has organized ridges but an ambiguous broad valley-floor counterpart.",
        "",
        "## Prior associations and novelty",
        "",
        "The focused novelty ledger covers the four retained Jezero footprints and their broad regional/target associations. Its source URLs, actual queries, access status and conclusions are included in `novelty_audit.json` and `docs/novelty-audit.md`. Nearby-region and exact-footprint findings are kept separate. A numerical-coordinate search alone has poor scholarly recall and does not establish novelty.",
        "",
        "Atacama/Mars analogues are already documented, and a search located an original author website with a Salar de Atacama Mars-analogue project and separate Jezero/CRISM work. Such prior regional/material work prevents a broad new-region claim, even where an exact 20 km terrain-mapping footprint remains unresolved. The contribution here is an inspectable characterization and evidence workflow. No absence-of-web-hit claim is promoted to a new association.",
        "",
        "## Transfer limits and next discriminating observations",
        "",
        "MOLA nominal spacing is not verified effective support: interpolation and profile gaps up to 12 km remain material even at a 1 km analysis spacing. Lunar polar support, scene geometry, mosaic seams and date differences require further checking. Dense overlapping search windows are not independent samples, and their rank counts are not campaign success rates. The finite sensitivity set omits a calibrated instrument-error model.",
        "",
        "A field campaign would need permissions, slope transects, substrate/grain-size descriptions and access review. Imagery does not establish traction, bearing strength, gravity response, vacuum, radiation, shielding, water resources, lunar temperatures or landing/base safety. Independent geologist review and new prospective targets would be needed to assess scientific usefulness beyond this exploratory characterization. No reviewer was contacted and no endorsement or field validation is claimed.",
        "",
        "## Reproduction",
        "",
        "Run `python scripts/build_research.py --expanded` to regenerate source-to-feature measurements, frozen rankings, camera packets and joined assessments from available raw data. Reacquisition scripts are separate, so ordinary reproduction does not need a token. `python scripts/verify_reproduction.py` compares the source hashes and full ranking tiers; evidence export hashes are recorded separately because image/literature annotations do not alter terrain ranks. `python -m pytest` and `npm run build` check the computation and interface build.",
        "",
        "## Sources and disclosure",
        "",
    ]
    lines += [
        f"- [{source['name']}]({source['url']}): {source['lineage']}."
        for source in b["sources"]
    ]
    lines += [
        "- [NASA Trek WMTS documentation](https://trek.nasa.gov/tiles/apidoc/trekAPI.html?body=mars), tile-source capability records retained.",
        "- [LROC WAC global morphology product](https://data.lroc.im-ldi.com/lroc/view_rdr/WAC_GLOBAL/), camera acquisition and processing lineage.",
        "",
        "The original supplied planning documents date November 4–5, 2026. Codex assisted with software, methods, visual assessment and report text. OpenCode model work, where available, is documented separately and is not an independent scientific panel. No public deployment, competition submission, organizer review or external scientific validation is implied by this release.",
    ]
    (REPORTS / "research_report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    finalize()
