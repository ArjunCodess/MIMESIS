"""Join measured discovery experiments without promoting their claim ceilings."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from src.ranking import canonical_hash

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "apps/web/public/research"
REPORTS = ROOT / "artifacts/reports"

RESOURCES = [
    ("NASA Earthdata Search", "HLS and EMIT discovery, quality products and protected observation access.", "https://search.earthdata.nasa.gov/"),
    ("NASA Worldview", "Visual and temporal context; screenshots do not replace measured source data.", "https://worldview.earthdata.nasa.gov/"),
    ("NASA Planetary Data System", "MOLA, CTX and CRISM observations, product labels and processing provenance.", "https://pds.nasa.gov/"),
    ("Lunar Reconnaissance Orbiter", "Existing LOLA/LROC terrain and imagery; lunar thermal context requires its own observations.", "https://pds-geosciences.wustl.edu/missions/lro/"),
    ("LRO Diviner", "Conditional thermal route, requiring matched physical quantities, quality and temporal support.", "https://pds-geosciences.wustl.edu/missions/lro/diviner.htm"),
    ("CSA RCM", "Conditional radar route after access, calibration and a named radar observable are established.", "https://donnees-data.asc-csa.gc.ca/en/dataset/rcm"),
    ("CSA RADARSAT-1", "Optional archived radar observations; no acquired radar experiment is implied.", "https://donnees-data.asc-csa.gc.ca/en/dataset/radarsat1"),
    ("CSA SAR tutorial", "Processing reference; radar backscatter is not interchangeable with optical brightness or DEM roughness.", "https://github.com/asc-csa/Synthetic_Aperture_Radar_Tutorial"),
    ("Copernicus Data Space", "Finer Earth DEMs and their fill, editing, water and height-error ancestry.", "https://dataspace.copernicus.eu/"),
    ("ESA Open Science Catalog", "Product discovery for a justified observable; catalogue access is not dataset acquisition.", "https://opensciencedata.esa.int/"),
    ("JAXA G-Portal", "Optional Earth observations when a specific product and process are selected.", "https://gportal.jaxa.jp/"),
]


def pending(identifier, title):
    return {"id": identifier, "title": title, "statement": "This experiment has not published a measured record. Missing observations are unknown.",
            "counts": [{"label": "Measured cases", "value": None}], "report": "plan-implementation.md", "record": "discovery_v9.json",
            "figure": None, "cases": [], "limitations": ["No completed result is inferred from an absent record."]}


def fraction(value):
    return "Not measured" if value is None else f"{100 * value:.2f}%"


def earth_section(record):
    summary = record["summary"]
    cases = []
    for row in record["blocks"]:
        cases.append({"id": row["id"], "label": row["id"], "state": row["status"], "latitude": row["latitude"], "longitude": row["longitude"],
                      "metrics": [{"label": "Mapped natural terrain, context", "value": fraction(row["masked_terrain"]["context_valid_fraction"])},
                                  {"label": "Mapped natural terrain, local", "value": fraction(row["masked_terrain"]["local_valid_fraction"])}],
                      "evidence": [f"{name}: {layer['status'].replace('_', ' ')}" for name, layer in row["layers"].items()],
                      "missing": row["missing_gate_reasons"]})
    return {"id": "earth", "title": "Earth eligibility", "statement": "The same 100 frozen locations face real land-cover, road, terrain and clear-imagery gates before a new transfer comparison. A mapped natural-land fraction is an upper bound while mandatory sources are missing.",
            "counts": [{"label": "Frozen contexts", "value": summary["frozen_contexts"]}, {"label": "Inventoried contexts", "value": summary["measured_contexts"]}, {"label": "Passing every mapped-source gate", "value": summary["eligible_contexts"]}],
            "report": "global_eligibility_v9.md", "record": "global_eligibility_v9.json", "figure": None,
            "cases": cases, "limitations": record["limitations"]}


def orbital_section(record):
    summary = record["summary"]
    box = record["roi"]["bbox_wsen"]
    cases = []
    for row in record["granules"]:
        quality = row.get("roi_quality")
        metrics = [{"label": "Acquisition", "value": row["time_start"]}]
        if quality is not None:
            metrics += [{"label": "Native centers in provisional box", "value": str(quality["native_roi_centers"])},
                        {"label": "Native centers passing quality flags", "value": str(quality["native_clear_centers"])},
                        {"label": "Valid native-center fraction, not area", "value": fraction(quality["clear_fraction_of_native_centers"])}]
        else:
            metrics.append({"label": "Native observation quality", "value": "Not measured"})
        cases.append({"id": row["granule_id"], "label": row["granule_id"], "state": row["analysis_state"],
                      "latitude": (box[1] + box[3]) / 2, "longitude": (box[0] + box[2]) / 2,
                      "metrics": metrics, "evidence": [f"{name}: {asset['state']}" for name, asset in row["assets"].items()],
                      "missing": ["independently_registered_geological_positive_and_matched_negative_controls"] + ([] if "spectral_summary" in row else ["quality_eligible_reflectance_and_uncertainty_ROI_analysis"])})
    return {"id": "spectra", "title": "Orbital mineral-feature test", "statement": "Actual EMIT masks, reflectance and uncertainty test what can be observed over a provisional Puga box. Puga is a known analogue. Native-pixel summaries do not identify minerals or establish an independent Earth–Mars association.",
            "counts": [{"label": "Declared seasonal scenes", "value": summary["expected_seasonal_granules"]}, {"label": "Masks acquired", "value": summary["acquired_masks"]}, {"label": "Scenes with usable native centers", "value": summary["scenes_with_quality_eligible_native_centers"]}, {"label": "Reflectance and uncertainty analyses", "value": summary["scenes_with_reflectance_and_uncertainty_analysis"]}],
            "report": "orbital_spectra_v9.md", "record": "orbital_spectra_v9.json", "figure": "orbital_spectra_v9.png" if (REPORTS / "orbital_spectra_v9.png").exists() else None,
            "cases": cases, "limitations": record["limitations"]}


def transfer_section(record):
    summary = record["summary"]
    return {"id": "transfer", "title": "Terrain transfer", "statement": "Exact context geometry, unused matched controls, independent references and source support determine whether a transfer comparison can be evaluated. Nominal catalogue footprints remain separate from valid stereo pixels and geological truth.",
            "counts": [{"label": "Actual CTX catalogue items inventoried", "value": summary["catalogue_item_count"]}, {"label": "Nominal local-footprint candidates", "value": summary["geometry_feasible_items"]}, {"label": "Complete transfer pairs", "value": summary["complete_transfer_pairs"]}, {"label": "New evaluation targets frozen", "value": summary["new_targets_frozen"]}],
            "report": "transfer_v9.md", "record": "transfer_v9.json", "figure": None,
            "cases": [{"id": row["target_id"], "label": row["target_id"], "state": row["state"], "latitude": None, "longitude": None,
                       "metrics": [{"label": "Target exposure", "value": row["exposure"].replace("_", " ")}, {"label": "Contact reference", "value": row["reference"]["state"].replace("_", " ")}],
                       "evidence": [f"Planetary body: {row['body']}", "Complete nomination/control pair" if row["pair"] else "No complete qualified pair"],
                       "missing": row["missing"] + row["reference"]["missing"]} for row in record["cases"]],
            "limitations": record["source_limits"]}


def build(root=ROOT):
    reports = root / "artifacts/reports"
    public = root / "apps/web/public/research"
    sections, sources = [], []
    for filename, identifier, title, normalize in [
        ("global_eligibility_v9.json", "earth", "Earth eligibility", earth_section),
        ("orbital_spectra_v9.json", "spectra", "Orbital mineral-feature test", orbital_section),
        ("transfer_v9.json", "transfer", "Terrain transfer", transfer_section),
    ]:
        path = reports / filename
        if not path.exists():
            sections.append(pending(identifier, title))
            continue
        record = json.loads(path.read_text(encoding="utf-8-sig"))
        sections.append(normalize(record))
        sources.append({"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "record_hash": record["record_hash"]})
        public.mkdir(parents=True, exist_ok=True)
        for suffix in [".json", ".md", ".png"]:
            asset = path.with_suffix(suffix)
            if asset.exists():
                shutil.copy2(asset, public / asset.name)
    result = {"id": "mimesis-discovery-v9", "status": "exploratory_observation_tests", "objective": "Find an exploration-relevant Earth–planet association that survives independent observations, matched alternatives and prior-work checks.",
              "claim": "Current evidence supports screening and explicitly bounded observations. A new analogue discovery, mineral identification and mapping-rehearsal benefit remain unestablished.",
              "sections": sections, "resources": [{"name": name, "role": role, "url": url} for name, role, url in RESOURCES], "sources": sources}
    result["record_hash"] = canonical_hash(result)
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    reports.mkdir(parents=True, exist_ok=True)
    public.mkdir(parents=True, exist_ok=True)
    for folder in [reports, public]:
        (folder / "discovery_v9.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    lines = ["# Discovery experiments V9", "", result["objective"], "", result["claim"], ""]
    for section in sections:
        lines += [f"## {section['title']}", "", section["statement"], "", "| Observation | Count |", "|---|---:|"]
        lines += [f"| {row['label']} | {row['value'] if row['value'] is not None else 'Not measured'} |" for row in section["counts"]]
        lines += ["", f"[Full record]({section['record']}) · [Methods and limits]({section['report']})", ""]
    lines += ["## Claim and observation boundaries", "", "Missing or inaccessible sources are unknown. Catalogue coverage, repeated pixels, acquisition dates and matching scores do not supply independent geological labels. Frozen V3-V8 records remain unchanged. The spectral box is not independently registered to field specimens. Contact utility needs a controlled rehearsal intervention and independent references. Optional thermal, radar, caves and biological routes are not completed experiments merely because their catalogue resources are linked.", "", f"Joined record SHA256: `{result['record_hash']}`.", ""]
    for folder in [reports, public]:
        (folder / "discovery_v9.md").write_text("\n".join(lines), encoding="utf-8")
    print("Published source-linked discovery experiments", result["record_hash"])
    return result


if __name__ == "__main__":
    build()
