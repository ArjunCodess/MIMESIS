"""Characterize acquired SIM3464 geology without treating it as blind truth."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil

from src.geology import (
    MarsWindow, characterize_window, export_native_geopackage,
    extract_reference_archive, mars_geojson, read_vector_layer, repair_units_for_analysis,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    config_path = root / "configs/geology_v6.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    raw = root / config["raw_directory"]
    report_dir = root / "artifacts/reports"
    public = root / "apps/web/public/research"
    derived = root / "data/derived/geology_v6"
    for directory in (report_dir, public, derived):
        directory.mkdir(parents=True, exist_ok=True)

    verified = []
    for declared in config["source"]["files"]:
        path = raw / declared["name"]
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if path.stat().st_size != declared["bytes"] or digest != declared["sha256"]:
            raise ValueError(f"Source verification failed: {path}")
        verified.append({**declared, "verified": True, "path": path.relative_to(root).as_posix()})
    archive = next(f for f in verified if f["name"].endswith(".zip"))
    extraction = extract_reference_archive(raw / archive["name"], raw, archive["sha256"])
    database = raw / config["source"]["geodatabase"]
    boundary, contacts, originals = tuple(read_vector_layer(database, name) for name in config["source"]["layers"])
    units, repairs = repair_units_for_analysis(originals)
    window = MarsWindow(**config["calibration_window"])
    jezero, clipped_units, clipped_contacts = characterize_window(window, boundary, contacts, units)
    targets = json.loads((root / config["prospective_targets_path"]).read_text(encoding="utf-8"))["targets"]
    prospective = []
    for target in targets:
        target_window = MarsWindow(id=target["id"], body=target["body"],
                                   latitude=target["latitude"], longitude=target["longitude"])
        summary, _, _ = characterize_window(target_window, boundary, contacts, units)
        prospective.append(summary)

    native_path = derived / "geology_v6_sim3464_native.gpkg"
    export_native_geopackage(native_path, (boundary, contacts, originals))
    geojson_path = derived / "geology_v6_jezero_mars.geojson"
    geojson_path.write_text(json.dumps(mars_geojson(window, (clipped_units, clipped_contacts)),
                                       indent=2, allow_nan=False) + "\n", encoding="utf-8")
    artifacts = []
    for path in (native_path, geojson_path):
        shutil.copyfile(path, public / path.name)
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        artifacts.append({"path": path.relative_to(root).as_posix(), "public_url": f"/research/{path.name}",
                          "bytes": path.stat().st_size, "sha256": digest})
    source = {**config["source"], "files": verified, "extraction": extraction,
              "native_crs_wkt": boundary.crs.to_wkt(),
              "native_layer_counts": {layer.name: len(layer.features) for layer in (boundary, contacts, originals)},
              "native_contact_types": dict(Counter(f.attributes["TYPE"] for f in contacts.features)),
              "analytical_geometry_repairs": repairs}
    result = {"id": config["id"], "source": source, "reference_policy": config["reference_policy"],
              "jezero": jezero, "prospective_targets": prospective, "artifacts": artifacts,
              "reproduce": "python scripts/characterize_geology.py",
              "lineage": {"config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
                          "module_sha256": hashlib.sha256((root / "src/geology.py").read_bytes()).hexdigest(),
                          "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}
    stats = jezero["contacts"]
    lines = ["# SIM3464 geology reference intake", "",
             f"The 20 km Jezero calibration square contains {jezero['unit_class_count']} mapped unit classes, "
             f"{jezero['unit_polygon_feature_count']} polygon features and {stats['total_length_km']:.3f} km of geological contact linework. "
             f"Its mapped coverage is {jezero['map_coverage_fraction']:.6%}. This characterizes a previously inspected reference; it does not measure prediction accuracy.",
             "", "| Contact TYPE | Source features intersecting square | Clipped length, km |",
             "|---|---:|---:|"]
    for kind, values in stats["by_certainty"].items():
        lines.append(f"| {kind} | {values['source_feature_count']} | {values['length_km']:.3f} |")
    lines += ["", f"The source TYPE inventory is {source['native_contact_types']}. Map-frame boundary lines are preserved in native exports "
              "and excluded from contact lengths and transect crossings. No inferred contacts are fabricated.", "",
              f"Unit union area is {jezero['unit_union_area_km2']:.6f} km², polygon overlap is {jezero['unit_overlap_area_km2']:.6f} km², "
              f"and the gap within mapped support is {jezero['unit_gap_within_map_km2']:.6f} km². "
              f"{len(repairs)} invalid original unit geometries required make_valid analytical copies. Native GeoPackage geometries retain the originals.", "",
              "The two centerline transects are geometric summaries of authored contacts. They cannot establish physical transition certainty or a mapping F1 score.", "",
              "| Prospective target | Map coverage | Center-to-map distance, km |", "|---|---:|---:|"]
    for target in prospective:
        lines.append(f"| {target['id']} | {target['map_coverage_fraction']:.6%} | {target['center_to_map_distance_km']:.3f} |")
    lines += ["", "No prospective window intersects the acquired SIM3464 map. Their unit counts and contacts remain null because coverage is missing; this does not mean those targets lack contacts.", "",
              config["reference_policy"]["registration_qualifier"], "",
              config["reference_policy"]["crs_conflict"], "",
              "Calculations use a 3,396,190 m Mars sphere and a local azimuthal equidistant projection for each window. "
              "The geographic clip is explicitly non-RFC7946 planetary GeoJSON. Earth EPSG:4326, Earth basemaps and automatic accuracy assessment are inappropriate for these coordinates.", "",
              f"Source: [{source['title']}]({source['url']}). Five source files pass byte-count and SHA-256 verification. "
              "The raster basemaps remain inside the verified archive; only geodatabase and coordinate-system files are extracted.", "",
              "Reproduce with `python scripts/characterize_geology.py`. Source hashes, layer counts, repairs, lengths by certainty and export checksums are in `geology_v6.json`."]
    for directory in (report_dir, public):
        (directory / "geology_v6.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        (directory / "geology_v6.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    prior = config["prior_work"]
    audit_path = root / prior["inherited_audit_path"]
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    access = json.loads((root / prior["source_access_path"]).read_text(encoding="utf-8"))
    refreshed = {s["id"]: s for s in prior["refreshed_sources"]}
    sources = [{**source, **refreshed.get(source["id"], {}),
                "access_records": [a for a in access if a["id"] == source["id"]]}
               for source in audit["sources"]]
    plan_rows = []
    plan_text = (root / "PLAN.md").read_text(encoding="utf-8")
    prior_work_section = plan_text.split("## 4. Prior scientific work and what it means for us", 1)[1].split("## 5.", 1)[0]
    for line in prior_work_section.splitlines():
        if line.startswith("| [") and len(line.split("|")) == 5:
            cells = [cell.strip() for cell in line.split("|")[1:-1]]
            links = [{"title": title, "url": url} for title, url in re.findall(r"\[([^]]+)\]\(([^)]+)\)", cells[0])]
            if links:
                plan_rows.append({"sources": links, "inherited_relevance": cells[1], "implication": cells[2],
                                  "evidence_level": "inherited PLAN.md bounded review; not newly spatially verified"})
    footprint_path = root / prior["candidate_footprints_path"]
    investigations = json.loads(footprint_path.read_text(encoding="utf-8"))["investigations"]
    footprints = {item["candidate_id"]: {"earth_footprint": item["earth_footprint"],
                                       "target_footprint": item["target_footprint"],
                                       "target_id": target_id,
                                       "coordinate_policy": "Inherited terrestrial lon/lat and planetary lon/lat rings; separate bodies, no cross-body spatial join"}
                  for target_id, investigation in investigations.items() for item in investigation["shortlist"]}
    prior_result = {"id": "prior-work-catalogue-v6", "status": "bounded_catalogue_novelty_not_established",
                    "sources": sources, "catalogues": prior["catalogues"], "plan_prior_work": plan_rows,
                    "historical_candidates": [{**c, **footprints.get(c["candidate_id"], {}),
                                               "release_role": "historical v4 lead; no reversal of v5 land-mask rejection"}
                                              for c in audit["candidates"]],
                    "rules": prior["rules"], "limits": audit["limits"],
                    "spatial_join_status": "not_performed_no_registered_literature_footprints_or_catalogue_features",
                    "source_access": access,
                    "lineage": {"audit_path": prior["inherited_audit_path"],
                                "audit_sha256": hashlib.sha256(audit_path.read_bytes()).hexdigest(),
                                "candidate_footprints_path": prior["candidate_footprints_path"],
                                "candidate_footprints_sha256": hashlib.sha256(footprint_path.read_bytes()).hexdigest(),
                                "plan_sha256": hashlib.sha256((root / "PLAN.md").read_bytes()).hexdigest()}}
    prior_lines = ["# Prior-work catalogue", "",
                   "The inherited review establishes prior Mojave, Anti-Atlas and Namibia analogue contexts. Exact footprint and task overlap remains unresolved, so neither an exact duplicate nor a novel discovery is established.", ""]
    for source in sources:
        prior_lines += [f"## {source['title']}", "", source["finding"], "",
                        source.get("verification", source["access"]), "", f"Source: {source['url']}", ""]
    prior_lines += ["## Catalogue access and spatial limits", "", prior["catalogues"][0]["limitation"], "",
                    "The JSON also preserves the broader PLAN.md source table and the historical candidate/source associations. "
                    "These entries are literature context, not independent transfer labels. No spatial join is reported because catalogue features and registered publication footprints were not available.", "",
                    *prior["rules"], "", "Reproduce with `python scripts/characterize_geology.py`. Source-access records distinguish retrieved abstracts, original PDFs, metadata and inaccessible catalogue features."]
    for directory in (report_dir, public):
        (directory / "prior_work_v6.json").write_text(json.dumps(prior_result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        (directory / "prior_work_v6.md").write_text("\n".join(prior_lines) + "\n", encoding="utf-8")
    print(json.dumps({"jezero_units": jezero["unit_class_count"], "contact_length_km": stats["total_length_km"],
                      "prospective_covered": sum(t["map_coverage_fraction"] > 0 for t in prospective),
                      "analytical_repairs": len(repairs), "prior_sources": len(sources)}))


if __name__ == "__main__":
    main()
