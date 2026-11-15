"""Rebuild all measured observations, rankings, visual assets and research reports."""

from pathlib import Path
import csv
import hashlib
import json
import platform
import shutil
import time
from datetime import datetime, timezone
import numpy as np
from scipy.ndimage import map_coordinates
from scipy.stats import spearmanr
from PIL import Image
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from src.terrain import (
    open_nasadem,
    open_pds,
    project_window,
    smooth_grid,
    features,
)
from src.ranking import rank, canonical_hash
from src.imagery import hls_context

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "apps/web/public/research"
PROCESSED = ROOT / "data/processed"
REPORTS = ROOT / "artifacts/reports"
for directory in (PUBLIC, PROCESSED, REPORTS, ROOT / "artifacts/figures"):
    directory.mkdir(parents=True, exist_ok=True)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def terrain_image(z, path, earth=False):
    good = np.isfinite(z)
    v = z[good]
    if not len(v):
        raise ValueError("Cannot render terrain with no valid samples")
    low, high = np.percentile(v, [2, 98])
    normalized = np.clip(
        (np.nan_to_num(z, nan=float(np.median(v))) - low) / max(high - low, 1), 0, 1
    )
    palette = (
        np.array(
            [
                [29, 47, 46],
                [76, 91, 75],
                [143, 144, 108],
                [195, 174, 131],
                [234, 216, 180],
            ]
        )
        if earth
        else np.array(
            [
                [54, 37, 31],
                [112, 67, 47],
                [170, 108, 69],
                [213, 159, 106],
                [241, 212, 171],
            ]
        )
    )
    indices = normalized * 4
    lower = np.minimum(indices.astype(int), 3)
    fraction = (indices - lower)[..., None]
    color = palette[lower] * (1 - fraction) + palette[lower + 1] * fraction
    dy, dx = np.gradient(np.nan_to_num(z, nan=float(np.median(v))))
    scale = max(float(np.std(np.hypot(dx, dy))), 1)
    shade = np.clip(0.85 + (-dx + dy) / (scale * 7), 0.55, 1.2)
    color = np.clip(color * shade[..., None], 0, 255).astype("uint8")
    color[~good] = [230, 226, 214]
    Image.fromarray(color).resize((960, 960), Image.Resampling.BICUBIC).save(path)


def tiers(z, source_step=125):
    result, grids = {}, {}
    for support in (500, 1000):
        smoothed = smooth_grid(z, source_step, support)
        # Interpolate to centered destination cells, without a half-cell offset.
        factor = support / source_step
        axis = np.arange(factor / 2 - 0.5, z.shape[0], factor)
        yy, xx = np.meshgrid(axis, axis, indexing="ij")
        grid = map_coordinates(
            smoothed, [yy, xx], order=1, mode="constant", cval=np.nan
        )
        grids[str(support)] = grid
        result[str(support)] = features(grid, support)
    result["eroded"] = features(grids["500"], 500, erode=True)
    return result, grids


def load_protocol(expanded):
    protocol = json.loads((ROOT / "configs/protocol.json").read_text())
    expansion = None
    if expanded:
        expansion = json.loads((ROOT / "configs/expansion.json").read_text())
        protocol = {
            **protocol,
            "id": expansion["id"],
            "parent_protocol": expansion["parent_protocol"],
            "earth_stride_m": expansion["stride_m"],
            "regions": expansion["regions"],
            "evaluation_status": expansion["status"],
            "selection_rule": expansion["selection_rule"],
            "scope_deviations": [
                "Exploratory expansion after inspecting v1; original held-out targets are reused",
                "Two bounded Earth regions, not a global search",
                "Overlapping windows are not independent samples",
                "No external reviewer or field validation",
                "No discovery or base-suitability claim follows from descriptor loss",
            ],
        }
    return protocol, expansion


def build(expanded=False):
    began = time.perf_counter()
    protocol, expansion = load_protocol(expanded)
    # Persist protocol before processing any ranking. It is never fitted to results.
    protocol_hash = canonical_hash(protocol)
    write_json(
        REPORTS / "frozen_protocol.json",
        {"protocol_hash": protocol_hash, "protocol": protocol},
    )
    earth = open_nasadem(ROOT / "data/raw/earth/nasadem/NASADEM_HGT_s24w069")
    mola = open_pds(
        ROOT / "data/raw/mars/mola/megt44n000hb.img",
        ROOT / "data/raw/mars/mola/megt44n000hb.xml",
        "mola",
    )
    lola = open_pds(
        ROOT / "data/raw/moon/lola/ldem_64.img",
        ROOT / "data/raw/moon/lola/ldem_64.xml",
        "lola",
    )
    print(
        "Decoded NASADEM, MOLA and LOLA with verified sizes and explicit byte order",
        flush=True,
    )
    source_manifest = []
    frozen_sources = ROOT / "configs/source_manifest_v3.json"
    source_paths = (
        [ROOT / entry["path"] for entry in json.loads(frozen_sources.read_text())]
        if expanded and frozen_sources.exists()
        else sorted((ROOT / "data/raw").rglob("*"))
    )
    for path in source_paths:
        if not path.is_file():
            continue
        digest = hashlib.file_digest(path.open("rb"), "sha256").hexdigest()
        source_manifest.append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": digest,
                "status": "interrupted_download_preserved"
                if path.suffix == ".part"
                else "empty_supplied_file"
                if not path.stat().st_size
                else "present",
            }
        )
    write_json(REPORTS / "source_manifest.json", source_manifest)
    regions = []
    if expanded:
        from measure_regions import measure_regions

        candidates, contexts, regions, imagery_record, attempted = measure_regions(
            ROOT, protocol, expansion, terrain_image
        )
    else:
        # One projected Earth field reused for every candidate. Source remains immutable.
        field, inverse = project_window(earth, -23.5, -68.5, 116000, 125)
        fields = {str(s): smooth_grid(field, 125, s) for s in (500, 1000)}
        np.savez_compressed(
            PROCESSED / "earth_projected.npz", elevation=field, spacing_m=125
        )
        terrain_image(fields["500"], PUBLIC / "earth.png", True)
        terrain_image(fields["1000"], PUBLIC / "earth-1000.png", True)
        imagery_mask, imagery_record = hls_context(
            ROOT / "data/raw/earth/hls", inverse, PUBLIC / "hls-context.png"
        )
        candidates = []
        contexts = {}
        attempted = 0
        # 1 km overlapping search; support/coverage masks determine the actual domain.
        for northing in range(-20000, 20001, protocol["earth_stride_m"]):
            for easting in range(-20000, 20001, protocol["earth_stride_m"]):
                attempted += 1
                measured, windows = {}, {}
                for support in (500, 1000):
                    axis = np.arange(-40000 + support / 2, 40000, support)
                    x, y = np.meshgrid(axis + easting, -axis + northing)
                    col, row = (x + 58000) / 125 - 0.5, (58000 - y) / 125 - 0.5
                    window = map_coordinates(
                        fields[str(support)],
                        [row, col],
                        order=1,
                        mode="constant",
                        cval=np.nan,
                    )
                    measured[str(support)] = features(
                        window, support, protocol["minimum_valid_fraction"]
                    )
                    windows[str(support)] = window
                measured["eroded"] = features(
                    windows["500"], 500, protocol["minimum_valid_fraction"], True
                )
                if not all(measured.values()):
                    continue
                longitude, latitude = inverse.transform(easting, northing)
                corners = [
                    inverse.transform(easting + dx, northing + dy)
                    for dx, dy in [
                        (-10000, -10000),
                        (10000, -10000),
                        (10000, 10000),
                        (-10000, 10000),
                        (-10000, -10000),
                    ]
                ]
                identifier = f"AT-{easting + 20000:05d}-{northing + 20000:05d}"
                hls_row = int((58000 - northing) / 125)
                hls_col = int((58000 + easting) / 125)
                imagery_coverage = float(
                    imagery_mask[
                        hls_row - 80 : hls_row + 80, hls_col - 80 : hls_col + 80
                    ].mean()
                )
                candidates.append(
                    {
                        "id": identifier,
                        "name": "Atacama study window",
                        "region": "Northern Chile",
                        "latitude": latitude,
                        "longitude": longitude,
                        "easting_m": easting,
                        "northing_m": northing,
                        "footprint": corners,
                        "features": measured,
                        "source_ids": ["nasadem"],
                        "image": "earth.png",
                        "reserved_hls_valid_fraction": imagery_coverage,
                    }
                )
                contexts[identifier] = windows["500"]
            if northing % 10000 == 0:
                print(
                    f"Earth sweep {northing:+} m; {len(candidates)} valid windows",
                    flush=True,
                )
    if not candidates:
        raise ValueError("No complete Earth windows; inspect coverage and masks")
    targets = []
    grids = {}
    for definition in protocol["targets"]:
        source = mola if definition["source"] == "mola" else lola
        z, target_inverse = project_window(
            source, definition["latitude"], definition["longitude"], 84000, 125
        )
        # 2 km padding absorbs the smoothing kernel; crop to 80 km after filtering.
        measured = {}
        target_grids = {}
        for support in (500, 1000):
            smoothed = smooth_grid(z, 125, support)
            axis = np.arange(-40000 + support / 2, 40000, support)
            x, y = np.meshgrid(axis, -axis)
            grid = map_coordinates(
                smoothed,
                [(42000 - y) / 125 - 0.5, (x + 42000) / 125 - 0.5],
                order=1,
                mode="constant",
                cval=np.nan,
            )
            measured[str(support)] = features(grid, support)
            target_grids[str(support)] = grid
        measured["eroded"] = features(target_grids["500"], 500, erode=True)
        if not all(measured.values()):
            raise ValueError(f"Required terrain missing for {definition['id']}")
        image = definition["id"] + ".png"
        terrain_image(target_grids["500"], PUBLIC / image)
        terrain_image(target_grids["1000"], PUBLIC / (definition["id"] + "-1000.png"))
        target = {
            **definition,
            "features": measured,
            "image": image,
            "footprint": [
                target_inverse.transform(x, y)
                for x, y in [
                    (-10000, -10000),
                    (10000, -10000),
                    (10000, 10000),
                    (-10000, 10000),
                    (-10000, -10000),
                ]
            ],
            "projection": f"AEQD centered {definition['latitude']}, {definition['longitude']}; radius {source.radius} m",
        }
        targets.append(target)
        grids[target["id"]] = target_grids
        print(
            f"Measured {target['name']}: {measured['500']['relief_m']:.1f} m local relief",
            flush=True,
        )
    rankings = {t["id"]: rank(candidates, t, protocol) for t in targets}
    rankings_1000 = {t["id"]: rank(candidates, t, protocol, 1000) for t in targets}
    benchmark = []
    investigations = {}
    candidate_lookup = {c["id"]: c for c in candidates}
    for target in targets:
        result = rankings[target["id"]]
        sensitivity = rankings_1000[target["id"]]
        a = [c["id"] for c in result["candidates"]]
        b = [c["id"] for c in sensitivity["candidates"]]
        nominal = sorted(
            result["candidates"], key=lambda c: (c["nominal_loss"], c["id"])
        )
        slope_only = sorted(
            result["candidates"], key=lambda c: (c["group_losses"][0], c["id"])
        )
        overlap = len(set(a[:10]) & set(b[:10])) / len(set(a[:10]) | set(b[:10]))
        b_positions = {key: i for i, key in enumerate(b)}
        correlation = float(
            spearmanr(np.arange(len(a)), [b_positions[key] for key in a]).statistic
        )
        benchmark.append(
            {
                "target_id": target["id"],
                "split": target["split"],
                "body": target["body"],
                "top10_jaccard_500_vs_1000": overlap,
                "rank_spearman": correlation,
                "robust_winner": a[0],
                "nominal_winner": nominal[0]["id"],
                "slope_only_winner": slope_only[0]["id"],
                "robust_minimum": result["candidates"][0]["robust_loss"],
                "rank_stability_warning": overlap < 0.6,
            }
        )
        from src.selection import freeze_shortlist

        rule = (
            expansion["selection_rule"]
            if expanded
            else {
                "minimum_context_separation_m": 20000,
                "slope_category_edges_deg": [1, 3, 8],
                "relief_category_edges_m": [100, 500, 1500],
                "maximum_context_coverage_difference": 0.02,
                "maximum_local_coverage_difference": 0.02,
            }
        )
        selected, roles, matches, unfilled = freeze_shortlist(
            result["candidates"], candidates, rule, protocol["scenario_seed"]
        )
        dossiers = []
        for identifier in selected:
            dossiers.append(
                {
                    "candidate_id": identifier,
                    "role": roles[identifier],
                    "matched_to": matches.get(identifier),
                    "claim_level": "screened_candidate",
                    "corroboration": [
                        {
                            "requirement": r,
                            "status": "unassessable",
                            "reason": "No separately acquired planetary imagery assessment has been performed",
                        }
                        for r in ["basin_floor", "ridge_margin", "relief_transition"]
                    ],
                    "novelty_status": "unresolved",
                    "novelty_queries": [],
                    "reviewer_status": "not_reviewed",
                    "contradictions": [],
                    "contradiction_assessment": "not_assessed",
                    "field_tests": [
                        "Slope transects to test DEM-scale relief",
                        "Surface and grain-size descriptions to test substrate assumptions",
                        "Site access and permit review before field planning",
                    ],
                }
            )
        investigations[target["id"]] = {
            "id": target["id"],
            "run_hash": result["run_hash"],
            "shortlist": dossiers,
            "planned_count": 6,
            "unfilled_slots": unfilled,
            "selection_rule": rule,
            "actual_count": len(dossiers),
            "scope_note": "The bounded tile cannot guarantee six mutually non-overlapping windows; no overlaps are silently substituted.",
            "claim": "Unresolved terrain analogue hypotheses; no discovery established",
        }
        for row in result["candidates"][:10]:
            c = candidate_lookup[row["id"]]
            name = c["id"] + ".png"
            if not (PUBLIC / name).exists():
                terrain_image(contexts[c["id"]][60:100, 60:100], PUBLIC / name, True)
            c["image"] = name
    sources = [
        {
            "id": "nasadem",
            "name": "NASADEM HGT v001",
            "body": "Earth",
            "url": "https://doi.org/10.5067/MEaSUREs/NASADEM/NASADEM_HGT.001",
            "role": "ranking",
            "units": "metres, EGM96",
            "encoding": "big-endian signed int16, 3601 square nodes",
            "nominal_spacing": "1 arc second",
            "lineage": "Reprocessed SRTM with ancillary fill sources; NUM file retained",
            "rights": "NASA Earthdata open data; retain product attribution",
        },
        {
            "id": "mola",
            "name": "MGS MOLA MEGDR",
            "body": "Mars",
            "url": "https://pds-geosciences.wustl.edu/missions/mgs/megdr.html",
            "role": "ranking",
            "units": "metres relative to GMM3 areoid",
            "encoding": "big-endian signed int16",
            "nominal_spacing": "128 pixels/degree, about 463 m at equator",
            "lineage": "MOLA observations and interpolation; profile gaps up to 12 km per supplied label",
            "rights": "NASA PDS; cite MOLA science team and Geosciences Node",
        },
        {
            "id": "lola",
            "name": "LRO LOLA LDEM 64",
            "body": "Moon",
            "url": "https://imbrium.mit.edu/DATA/LOLA_GDR/CYLINDRICAL/IMG/",
            "role": "ranking",
            "units": "metres above 1737.4 km reference sphere",
            "encoding": "little-endian signed int16, DN times 0.5",
            "nominal_spacing": "64 pixels/degree, about 474 m at equator",
            "lineage": "LOLA altimetry with gridding and interpolation; 45 degree band seams possible",
            "rights": "NASA PDS / MIT LOLA science team; retain attribution",
        },
        {
            "id": "hls",
            "name": "HLS Landsat L30 v2.0",
            "body": "Earth",
            "url": "https://hls.gsfc.nasa.gov/",
            "role": "reserved_context",
            "units": "surface reflectance DN times 0.0001",
            "encoding": "GeoTIFF, Fmask supplied",
            "nominal_spacing": "30 m",
            "lineage": "Separate Landsat acquisition on 2025-12-25; no image interpretation used to score or validate terrain",
            "rights": "NASA HLS / USGS Landsat, open data attribution",
        },
    ]
    generated = datetime.now(timezone.utc).isoformat()
    bundle = {
        "schema_version": "1.0",
        "generated_at": generated,
        "protocol_hash": protocol_hash,
        "data_hash": canonical_hash(source_manifest),
        "protocol": protocol,
        "sources": sources,
        "earth": {
            "name": "Atacama, northern Chile",
            "tile": "s24w069",
            "bounds": [-69, -24, -68, -23],
            "center": [-68.5, -23.5],
            "extent_m": 116000,
            "image": "earth.png",
            "attempted_windows": attempted,
            "valid_windows": len(candidates),
            "stride_m": 1000,
            "projection": "WGS84 AEQD, center -23.5 / -68.5",
            "independence": "Highly overlapping windows; counts are not independent replicates",
        },
        "regions": regions,
        "experiment": {
            "version": "v3" if expanded else "v1",
            "status": expansion["status"] if expanded else "Bounded pilot",
            "parent_archive": "artifacts/archive/expansion-v2" if expanded else None,
        },
        "targets": targets,
        "candidates": candidates,
        "rankings": rankings,
        "rankings_1000": rankings_1000,
        "benchmark": benchmark,
        "reserved_imagery": imagery_record,
        "investigations": investigations,
        "source_manifest": source_manifest,
        "runtime": {"python": platform.python_version(), "numpy": np.__version__},
        "claim": "Measured terrain screening with unresolved corroboration and novelty",
    }
    write_json(PUBLIC / "bundle.json", bundle)
    write_json(REPORTS / "benchmark.json", benchmark)
    write_json(REPORTS / "investigations.json", investigations)
    write_json(
        PROCESSED / "features.json", {"targets": targets, "candidates": candidates}
    )
    with (REPORTS / "rankings.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "target",
                "candidate",
                "rank",
                "nominal_loss",
                "robust_loss",
                "latitude",
                "longitude",
            ],
        )
        writer.writeheader()
        for target_id, result in rankings.items():
            for row in result["candidates"]:
                c = candidate_lookup[row["id"]]
                writer.writerow(
                    {
                        "target": target_id,
                        "candidate": c["id"],
                        "rank": row["rank"],
                        "nominal_loss": row["nominal_loss"],
                        "robust_loss": row["robust_loss"],
                        "latitude": c["latitude"],
                        "longitude": c["longitude"],
                    }
                )
    plot_results(bundle)
    report(bundle, time.perf_counter() - began)
    for name in (
        "research_report.md",
        "benchmark.json",
        "investigations.json",
        "source_manifest.json",
        "frozen_protocol.json",
        "rankings.csv",
    ):
        shutil.copy2(REPORTS / name, PUBLIC / name)
    print(
        f"Built research bundle: {len(candidates)} real Earth windows, {len(targets)} planetary cases in {time.perf_counter() - began:.1f}s",
        flush=True,
    )

    if expanded:
        from prepare_evidence import prepare
        from finalize_research import finalize

        prepare()
        finalize()


def plot_results(bundle):
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), facecolor="#f4f1e8")
    labels = [t["name"] for t in bundle["targets"]]
    axes[0].barh(
        labels, [b["robust_minimum"] for b in bundle["benchmark"]], color="#a45334"
    )
    axes[0].set(xlabel="Minimum robust discrepancy, lower is closer", xlim=(0, 1))
    axes[1].barh(
        labels,
        [b["top10_jaccard_500_vs_1000"] for b in bundle["benchmark"]],
        color="#526d59",
    )
    axes[1].axvline(0.6, color="#a45334", linestyle="--", label="Provisional warning")
    axes[1].set(xlabel="Top-10 Jaccard, 500 m vs 1 km", xlim=(0, 1))
    for ax in axes:
        ax.set_facecolor("#f4f1e8")
        ax.spines[["top", "right"]].set_visible(False)
    axes[1].legend(loc="lower right")
    fig.suptitle("MIMESIS bounded pilot: measured discrepancy and scale sensitivity")
    fig.tight_layout()
    fig.savefig(ROOT / "artifacts/figures/pilot_results.png", dpi=180)
    plt.close(fig)


def report(bundle, seconds):
    lines = [
        "# MIMESIS bounded terrain analogue investigation",
        "",
        f"Generated {bundle['generated_at']}. Protocol `{bundle['protocol_hash']}`.",
        "",
        "## Finding",
        "",
        f"The pipeline screened {len(bundle['candidates'])} overlapping 20 km Earth windows against six Moon/Mars windows using real NASADEM, MOLA and LOLA elevations. It produced reproducible terrain nominations. None is a corroborated or novel analogue: separate planetary imagery assessments, literature novelty searches and independent review have not been completed.",
        "",
        "## Research question and domain",
        "",
        "Can support-matched terrain descriptors nominate Earth windows for regional geomorphological mapping rehearsal? The bounded search uses the single supplied NASADEM s24w069 tile, 24 to 23 degrees south and 69 to 68 degrees west. This pilot cannot establish global optimality or generalization to other terrestrial regions.",
        "",
        "## Methods",
        "",
        "The protocol was serialized before ranking. Three development and three held-out target windows include both bodies. No parameters were tuned after viewing held-out results. These splits document the computation; without relevance labels they do not measure predictive accuracy.",
        "",
        "Each body uses an azimuthal equidistant projection centered on its window. Earth uses WGS84; Mars uses the 3396 km MOLA sphere; the Moon uses the 1737.4 km LOLA sphere. NASADEM is big-endian, MOLA is big-endian and LOLA is little-endian with half-metre scaling. Absolute elevation is excluded from cross-body scoring. LOLA reference radius is not added to height.",
        "",
        "Source rasters are bilinearly sampled on a 125 m staging grid, then Gaussian smoothed with FWHM equal to each 500 or 1000 m analysis grid spacing. Oversampling is numerical staging and adds no source detail. All descriptors use 20 km local and 80 km context windows with at least 95% valid area in both tiers; derivative stencils touching nodata are masked. NASADEM SWB water is masked. Interpolated planetary cells cannot be identified without source count products.",
        "",
        "The slope group uses shared-bin Wasserstein-1 distance. Relief/position uses local 95th-minus-5th percentile relief and 2 km Gaussian topographic-position standard deviation. Organization uses planar-detrended residual RMS and gradient-tensor anisotropy. Context uses 80 km robust relief and elevation standard deviation. Group budgets are 0.40, 0.25, 0.15 and 0.20. Each scalar discrepancy is squared after clipping at one with the explicit tolerances in the frozen protocol. Those tolerances are engineering assumptions, not expert calibration.",
        "",
        "Robust discrepancy is the maximum over nominal, 32 seeded weight perturbations, the alternative grid spacing and one-cell mask erosion. This finite sensitivity set is not a confidence interval or instrument uncertainty model. Rank ties use nominal discrepancy and stable ID. Missing mandatory data excludes a window.",
        "",
        "## Results",
        "",
        "| Target | Split | Robust minimum | Top-10 Jaccard | Rank correlation |",
        "|---|---|---:|---:|---:|",
    ]
    for t, b in zip(bundle["targets"], bundle["benchmark"]):
        lines.append(
            f"| {t['name']} | {t['split']} | {b['robust_minimum']:.5f} | {b['top10_jaccard_500_vs_1000']:.3f} | {b['rank_spearman']:.3f} |"
        )
    lines += [
        "",
        "Full rankings and baseline winners are in rankings.csv and benchmark.json. Different baseline winners are descriptive; no independent labels establish which method is scientifically better.",
        "",
        "## Frozen investigation outcomes",
        "",
        "| Target | Nominations and alternatives retained | Corroboration | Novelty |",
        "|---|---:|---|---|",
    ]
    for t in bundle["targets"]:
        inv = bundle["investigations"][t["id"]]
        lines.append(
            f"| {t['name']} | {inv['actual_count']} of 6 planned | Unassessable | Unresolved |"
        )
    lines += [
        "",
        "Nominations are greedily selected without local-footprint overlap. Alternatives are nominal-loss matched from the remaining ranked pool and must also avoid all retained footprints. Where the bounded tile cannot supply six distinct windows, the shortfall is published. The pilot does not replace missing alternatives with overlapping pseudo-replicates.",
        "",
        "The supplied HLS scene is reserved Earth context and never enters the terrain rank. Its reflectance is not a mineral validation label. No THEMIS or LROC imagery rubric has been applied. Empty contradiction lists mean not assessed, not absence of contradictions. Literature used during planning is not a completed footprint-specific novelty audit.",
        "",
        "## Limitations and next evidence",
        "",
        "The strongest release claim is measured screening. MOLA's nominal 463 m grid contains interpolation and profile gaps of up to 12 km, so 500 m spacing cannot be described as verified effective support. The 1 km tier also does not resolve that source limitation. Polar LOLA sampling and map seams need independent checking, especially for Shackleton. Earth and planetary acquisition epochs differ. Morphology can agree despite different origins, material properties and environmental conditions.",
        "",
        "The single Earth tile is a reduced scope relative to the planned two-region minimum. Candidate counts reflect an overlapping 1 km search, not independent trials. There are no task-compatible labeled controls, field results or external reviewers. The provisional 0.35 screening threshold has no calibrated endorsement meaning. No result demonstrates traction, radiation shielding, water resources, thermal conditions, vacuum, bearing strength, landing safety or permanent-base suitability.",
        "",
        "A stronger association requires separately acquired planetary imagery and masked Earth imagery over every retained footprint, a blinded requirement-level assessment, a dated nearby-name/footprint/association literature search, and review of alternative geological explanations. Field slope transects and substrate measurements would test the transfer assumptions. Negative and unavailable evidence must remain published.",
        "",
        "## Reproduction and provenance",
        "",
        "Run `python scripts/acquire.py mola lola`, `python scripts/build_research.py`, and `python -m pytest`. Source byte lengths and SHA-256 checksums are in source_manifest.json. The application and API use the same exported measurements and scoring implementation. Run hashes include the frozen protocol, target descriptors, candidate descriptors, support and weights. Generated timestamps and build timing are outside ranking hashes.",
        "",
        f"Processing time for this build: {seconds:.1f} seconds. Python {platform.python_version()}, NumPy {np.__version__}.",
        "",
        "## Sources",
        "",
    ]
    lines += [
        f"- [{s['name']}]({s['url']}): {s['role']}; {s['lineage']}."
        for s in bundle["sources"]
    ]
    lines += [
        "",
        "## Disclosure",
        "",
        "The supplied planning documents date November 4 and 5, 2026 and remain preserved. Implementation, methods text and tests were produced with Codex assistance at the user's request. No independent scientist or organizer has reviewed this release. Eligibility, submission deadline, publication and event acceptance are not certified by this software. No competition submission was made.",
    ]
    (REPORTS / "research_report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--expanded", action="store_true")
    parser.add_argument(
        "--pilot",
        action="store_true",
        help="Rebuild the archived one-tile design instead of the current expansion",
    )
    args = parser.parse_args()
    build(not args.pilot)
