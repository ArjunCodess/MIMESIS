"""Join frozen v4 rankings with authored evidence, claim decisions and search logs."""

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from src.claims import ClaimReview, release_claim
from src.evidence import assess_packets
from src.ranking import canonical_hash

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "apps/web/public/research"
REPORTS = ROOT / "artifacts/reports"


def finalize():
    data = json.loads((PUBLIC / "discovery.json").read_text())
    packets = json.loads((REPORTS / "discovery_evidence_packets.json").read_text())
    imagery = json.loads((REPORTS / "planetary_imagery.json").read_text())
    rubric = json.loads((ROOT / "configs/corroboration_rubric.json").read_text())
    observations = json.loads(
        (ROOT / "configs/discovery_visual_assessments.json").read_text()
    )
    novelty = json.loads((ROOT / "configs/discovery_novelty_audit.json").read_text())
    authored = [
        ClaimReview.model_validate(r)
        for r in json.loads((ROOT / "configs/discovery_claim_reviews.json").read_text())
    ]
    investigations, counts = assess_packets(
        data, packets, imagery, rubric, observations, novelty
    )
    lookup = {c["id"]: c for c in data["candidates"]}
    history_path = REPORTS / "discovery_claim_history.json"
    history = json.loads(history_path.read_text()) if history_path.exists() else []
    leads = []
    for tid, investigation in investigations.items():
        investigation["claim"] = (
            "Exploratory source-linked remote characterization; no new analogue discovery established"
        )
        investigation["scope_note"] = (
            "Three frozen nominations and three matched alternatives with non-overlapping 80km contexts; all 36 outcomes retained"
        )
        rows = {
            r["id"]: r
            for r in data["runs"]["regional_geomorphological_mapping"][tid]["500"][
                "candidates"
            ]
        }
        for dossier in investigation["shortlist"]:
            cid = dossier["candidate_id"]
            review = next(
                (r for r in authored if r.target_id == tid and r.candidate_id == cid),
                None,
            )
            decision = release_claim(dossier, rows[cid], review)
            dossier["claim_level"] = decision["claim_level"]
            dossier["claim_decision"] = decision
            dossier["target_id"] = tid
            dossier["earth_footprint"] = lookup[cid]["footprint"]
            dossier["target_footprint"] = next(
                t["footprint"] for t in data["targets"] if t["id"] == tid
            )
            dossier["field_tests"] = [
                "Survey slope transects across the mapped transition to test raster support",
                "Describe substrate and grain sizes to test the material-transfer limits",
                "Map human modification and source-date differences",
                "Obtain site-specific permission and an access assessment before a campaign",
            ]
            previous = next(
                (
                    h
                    for h in reversed(history)
                    if h["candidate_id"] == cid and h["target_id"] == tid
                ),
                None,
            )
            if previous is None:
                history.append(
                    {
                        "candidate_id": cid,
                        "target_id": tid,
                        "at": data["frozen_at"],
                        "claim_level": "screened_candidate",
                        "reason": "Frozen nomination or matched alternative before imagery assessment",
                        "rank_run_hash": investigation["run_hash"],
                    }
                )
            if (
                previous["claim_level"] if previous else "screened_candidate"
            ) != decision["claim_level"]:
                history.append(
                    {
                        "candidate_id": cid,
                        "target_id": tid,
                        "at": datetime.now(timezone.utc).isoformat(),
                        **decision,
                        "rank_run_hash": investigation["run_hash"],
                    }
                )
            if review is not None:
                candidate = lookup[cid]
                packet = dossier["imagery_packet"]
                leads.append(
                    {
                        "candidate_id": cid,
                        "target_id": tid,
                        "claim_level": decision["claim_level"],
                        "statement": f"A source-linked regional mapping hypothesis centered at {candidate['latitude']:.5f}, {candidate['longitude']:.5f}. The observed floor/margin arrangement passes the frozen model-assisted image rubric. Prior analogue work prevents a new-region claim; exact task/footprint novelty remains unresolved.",
                        "gates": [
                            {
                                "name": "Robust terrain screening",
                                "state": "passes provisional cutoff",
                                "reason": f"Robust loss {rows[cid]['robust_loss']:.6f}; support and mask sensitivities retained. Rank stability is diagnostic, not a probability.",
                            },
                            {
                                "name": "Separate camera observations",
                                "state": dossier["assessment_outcome"],
                                "reason": f"Clear Earth coverage {packet['earth_local_clear_fraction']:.2%} locally and {packet['earth_context_clear_fraction']:.2%} contextually; all mandatory visible requirements supported.",
                            },
                            {
                                "name": "Novelty audit",
                                "state": "known analogue context; exact association unresolved",
                                "reason": "Actual query log and prior studies are published. Coordinate differences do not establish novelty.",
                            },
                            {
                                "name": "Independent review",
                                "state": "not performed",
                                "reason": "Assessor also implemented the screening. No expert endorsement or field validation is implied.",
                            },
                        ],
                        "limitations": dossier["contradictions"]
                        + [decision.get("limitation", "No discovery is established")],
                        "earth_image": packet["earth_image"],
                        "planetary_image": packet["planetary_image"],
                    }
                )
    evidence = {
        "investigations": investigations,
        "assessment_summary": counts,
        "rubric": rubric,
        "novelty": novelty,
        "claim_reviews": [r.model_dump() for r in authored],
        "screening_record_hash": data["record_hash"],
    }
    evidence["evidence_hash"] = canonical_hash(evidence)
    (REPORTS / "discovery_investigations.json").write_text(
        json.dumps(evidence, indent=2), encoding="utf-8"
    )
    history_path.write_text(json.dumps(history, indent=2), encoding="utf-8")
    findings = {
        "headline": "Three characterized hypotheses; a new analogue discovery is not established",
        "conclusion": f"The six-region experiment measured {len(data['candidates']):,} valid windows and froze 36 comparisons. {counts.get('provisional_visual_support', 0)} comparisons met the visible-landform rubric in a model-assisted assessment. The deeper literature search found prior analogue work around the promising settings, so this release reports new source-linked characterizations and preserves unresolved novelty instead of asserting a new discovery.",
        "leads": leads,
        "remaining": [
            "Independent geologist review of the 36 frozen panels and task tolerances",
            "Exact geological-unit and published-footprint overlap review, including non-indexed and unpublished analogue campaigns",
            "Field slope transects, substrate descriptions and access/permission checks",
            "A verified CRISM/EMIT pair with quality masks, wavelength/response metadata and uncertainty before any mineral-similarity claim",
            "Calibrated time/season/quality-controlled thermal products before activating thermal context; temperature never establishes lunar environmental equivalence",
            "Official competition rule and submission verification; the challenge page returned 502 during access",
        ],
    }
    (PUBLIC / "discovery_findings.json").write_text(
        json.dumps(findings, indent=2), encoding="utf-8"
    )
    for name in [
        "discovery_investigations.json",
        "discovery_claim_history.json",
        "discovery_evidence_packets.json",
    ]:
        shutil.copy2(REPORTS / name, PUBLIC / name)
    (PUBLIC / "syrtis_novelty_audit.json").write_text(
        json.dumps(novelty, indent=2), encoding="utf-8"
    )
    finer = json.loads((REPORTS / "finer_support.json").read_text())
    lines = [
        "# MIMESIS discovery experiment v4",
        "",
        findings["conclusion"],
        "",
        f"Screening record `{data['record_hash']}`. Evidence record `{evidence['evidence_hash']}`.",
        "",
        "## Search and independent evidence",
        "",
        "This is a new exploratory search after v3, not a replacement held-out success. All six original target AOIs were already examined; no untouched holdout or discovery-accuracy claim is made. Regions, weights, classes and selection rules were frozen before the new measurements. Screening descriptors exclude the independent HLS/CTX/WAC observations.",
        "",
        "| Region | Valid windows | Excluded windows |",
        "|---|---:|---:|",
    ]
    lines += [
        f"| {r['region_id']} | {r['valid_windows']} | {r['excluded_windows']} |"
        for r in data["acquisition"]
    ]
    lines += [
        "",
        "Lanzarote is a known analogue setting but cannot supply an 80km terrestrial context under this rule. The water/missing-data rule excludes all of its windows rather than shrinking the task after viewing results. The six 232km projection grids cover approximately 323,000 square kilometres, including buffers and ocean; this falls below the planning aspiration of 0.5–1 million square kilometres. Dense 3km-stride windows are overlapping observations, not independent samples.",
        "",
        "## All frozen outcomes",
        "",
        "| Target | Candidate | Role | Outcome | Claim |",
        "|---|---|---|---|---|",
    ]
    for tid, inv in investigations.items():
        lines += [
            f"| {tid} | {d['candidate_id']} | {d['role']} | {d['assessment_outcome']} | {d['claim_level']} |"
            for d in inv["shortlist"]
        ]
    lines += [
        "",
        "The assessor viewed all six 36-case evidence sheets after IDs were frozen and knew shortlist roles. Numerical ranks were omitted from the sheets, but this is not independent blinding. Missing clear coverage is unassessable; the Isidis target lacks the required margin configuration for this task and is recorded as a target/task mismatch. The new lunar Mojave comparison remains ambiguous rather than being promoted because it has clear imagery.",
        "",
        "## Finer local terrain comparison",
        "",
        "A separately acquired 20m-posted CTX stereo product supports a 100m analysis comparison over the Jezero 20km window. Smoothing is Gaussian with FWHM equal to analysis spacing. CTX is registered to MOLA, so local stereo information is separate while absolute control is shared. The analysis grid is not a calibrated claim of effective resolution. The selected Syrtis stereo product has zero valid local coverage; the selected polar Kaguya product has only partial coverage. Neither supplies a valid finer comparison.",
        "",
        "| Window | Valid fraction | Median slope, degrees | 90th slope, degrees | Relief, metres |",
        "|---|---:|---:|---:|---:|",
    ]
    jezero = next(r for r in finer if r["target_id"] == "jezero")
    for name, measured in [("Jezero CTX stereo", jezero["planetary"])] + [
        (r["candidate_id"], r["earth"]) for r in jezero["earth_comparisons"]
    ]:
        lines.append(
            f"| {name} | {measured['valid_fraction']:.4f} | {measured['slope_median_deg']:.3f} | {measured['slope_p90_deg']:.3f} | {measured['relief_m']:.1f} |"
        )
    lines += [
        "",
        "This finer characterization is descriptive and was not used to select or retune candidates. Similar coarse loss can coexist with different local slope distributions. The comparison does not establish shared origin, substrate or navigation performance.",
        "",
        "## Prior work and novelty",
        "",
        "The bounded review preserves actual web queries and eight Crossref queries with 20 returned records each. Returned titles and available abstracts were screened; not every full text was read. Broad known analogues are controls. Bristol Dry Lake has prior Mars lacustrine work, the Anti-Atlas has a published Jezero/Midway material/biosignature association, and regional structural mapping has linked Namibian and Syrtis investigations. These findings defeat broad new-region claims. Exact-footprint/task novelty remains unresolved, not disproved or proven by a numerical-coordinate search.",
        "",
    ]
    lines += [
        f"- [{s['title']}]({s['url']}): {s['finding']}" for s in novelty["sources"]
    ]
    lines += [
        "",
        "## Complementary terrain sites",
        "",
        "The second task uses frozen 4km subwindows and physical class rules. Coverage averages closest bounded descriptor matches for each target class, then takes the minimum across 500m, 1km and eroded-mask scenarios. Empty or missing target classes score zero. Matching subwindows may be reused; this measures terrain-type representation rather than replicated campaign area. Each site must pass the individual terrain cutoff and each pair must have non-overlapping 80km contexts.",
        "",
        "| Target | Single | Top two | Selected pair | Gain over top two | Random mean |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    gains = []
    for tid, suite in data["suites"]["terrain_diversity_sampling"].items():
        gain = suite["selected"]["objective"] - suite["top_two"]["objective"]
        gains.append(gain)
        lines.append(
            f"| {tid} | {suite['single']['objective']:.3f} | {suite['top_two']['objective']:.3f} | {suite['selected']['objective']:.3f} | {gain:.3f} | {suite['random_pair_mean']:.3f} |"
        )
    lines += [
        "",
        f"Median gain over the constrained independently ranked top two is {np.median(gains):.3f}, compared with the planning aspiration of 0.10. This is an optimization-formula result on reused targets, not a held-out or independently reviewed usefulness effect. The evaluated shortlist is the best 50 eligible candidates plus each requirement's best representative; the result is not a global pair optimum. The rank and pair objectives do not include logistics, permission, thermal conditions, mineral abundance, gravity, pressure or radiation.",
        "",
        "## Reproduction and remaining work",
        "",
        "Run `python scripts/build_discovery.py --fresh`, `python scripts/prepare_review.py`, and `python scripts/finalize_discovery.py` after acquiring the declared sources. `scripts/verify_discovery.py` checks raw-to-ranking and selection reproduction. The original v3 serving record and protocol are preserved; its source list is frozen so unrelated new acquisitions cannot silently alter its data hash. The six-region experiment has its own source manifest, protocol, code digest and record hash.",
        "",
        "The optional spectral module implements response matching, continuum removal, absorption descriptors and SAM with missing-band abstention. No verified CRISM/EMIT pair was acquired, so the mineral objective remains unavailable. Thermal products, field validation, independent experts and official competition submission remain explicitly incomplete. The source-linked capability audit states which documentation items are implemented, conditional or external.",
        "",
        "Model-assisted observations and claim reviews are disclosed. No new analogue discovery, first-in-literature result, expert endorsement, field readiness or permanent-base suitability is established.",
    ]
    ablation_path = REPORTS / "support_ablation.json"
    if ablation_path.exists():
        ablation = json.loads(ablation_path.read_text())
        lines += [
            "",
            "## Support-treatment ablation",
            "",
            "The no-Gaussian ablation removes smoothing at 500m and eroded tiers while holding the 1km sensitivity tier, candidate domain, weights and cutoffs fixed. Bilinear staging remains; this diagnoses support-treatment sensitivity rather than validating an unsmoothed method.",
            "",
            "| Target | Top-10 Jaccard, matched versus unsmoothed |",
            "|---|---:|",
        ]
        lines += [
            f"| {row['target_id']} | {row['top10_jaccard']:.3f} |" for row in ablation
        ]
    evaluation_path = REPORTS / "discovery_evaluation.json"
    if evaluation_path.exists():
        performance = json.loads(evaluation_path.read_text())["latency"]
        lines += [
            "",
            "## Measured serving boundary",
            "",
            f"On {performance['machine']} with {performance['processor']} and Python {performance['python']}, 100 warm requests per route yielded rank p95 {performance['ranking_p95_seconds']:.3f}s and suite p95 {performance['suite_p95_seconds']:.3f}s. {performance['boundary']}",
            "",
            "The provisional median suite gain target of 0.10 is not met. There are no independent usefulness labels, so the project cannot infer scientific superiority from its own descriptor objective.",
        ]
    report = "\n".join(lines) + "\n"
    (REPORTS / "discovery_report.md").write_text(report, encoding="utf-8")
    (PUBLIC / "discovery_report.md").write_text(report, encoding="utf-8")
    fig, ax = plt.subplots(figsize=(9, 4.5), layout="constrained")
    bars = ax.barh(
        [k.replace("_", " ") for k in counts], list(counts.values()), color="#547969"
    )
    ax.bar_label(bars, padding=5)
    ax.set_title("36 frozen comparisons: model-assisted evidence outcomes")
    ax.set_xlabel("Selected comparisons, not independent samples")
    fig.savefig(ROOT / "artifacts/figures/v4-assessment-outcomes.png", dpi=180)
    plt.close(fig)
    print(
        "Published evidence outcomes:",
        dict(Counter(counts)),
        "; no new discovery established",
    )


if __name__ == "__main__":
    finalize()
