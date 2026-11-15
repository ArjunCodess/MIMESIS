"""Inventory frozen EMIT seasonal assets and characterize available native ROIs."""

import argparse
import hashlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import numpy as np
import requests
from netCDF4 import Dataset
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from src.orbital_spectra import (EmitMask, acquire_emit_rectangle, diagnostic_availability,
    read_emit_roi, read_derived_emit_roi, read_crism_wavelength_table, sha256,
    reference_emit_approximation, fixed_continuum_feature, compare_fixed_features, roi_centers)
from src.laboratory import ControlProtocol, read_archive
from src.spectra import Spectrum


def save_spectral_figure(spectra, masked_intervals, output):
    """Plot measured reflectance, supplied pixel uncertainty and retained support."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    summary = spectra.descriptive_summary()
    wave = spectra.wavelength_um
    means = np.array([np.nan if x is None else x for x in summary["mean_reflectance"]])
    errors = np.array([np.nan if x is None else x for x in summary["mean_supplied_pixel_posterior_sd"]])
    counts = np.asarray(summary["valid_native_centers_per_channel"])
    values = np.where(spectra.valid, spectra.reflectance, np.nan)
    lower, upper = np.full(len(wave), np.nan), np.full(len(wave), np.nan)
    for band in np.flatnonzero(counts):
        lower[band], upper[band] = np.nanquantile(values[:, band], [.1, .9])
    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True,
                             gridspec_kw={"height_ratios": [3, 1, 1]}, layout="constrained")
    axes[0].fill_between(wave, lower, upper, color="#94b6cb", alpha=.4,
                         label="10th-90th percentile across retained centers")
    axes[0].plot(wave, means, color="#14506b", linewidth=1.3, label="Mean retained reflectance")
    axes[0].set_ylabel("Surface reflectance")
    axes[0].legend(frameon=False, fontsize=8)
    axes[1].plot(wave, errors, color="#8c5e34", linewidth=1.2)
    axes[1].set_ylabel("Mean pixel\nposterior SD")
    axes[2].step(wave, counts, where="mid", color="#355644", linewidth=1.2)
    axes[2].set_ylabel("Retained native\ncenters")
    axes[2].set_xlabel("Wavelength (micrometres)")
    for ax in axes:
        for lo, hi in masked_intervals:
            ax.axvspan(lo, hi, color="#d3d3d3", alpha=.7)
        ax.grid(axis="y", alpha=.15)
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Puga EMIT native ROI: exploratory known-control observation", fontsize=14)
    axes[0].set_title(spectra.source_id, fontsize=8, loc="left")
    fig.supxlabel("Grey spans: fixed atmospheric exclusions. Pixel spread and supplied SD are not confidence intervals.\nProvisional bbox; no independently registered geological controls or mineral identification.", fontsize=9)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/orbital_spectra_v9.json"))
    parser.add_argument("--comparison-config", type=Path, help="Run separately versioned cross-observable follow-up, preserving V9 outputs")
    parser.add_argument("--output", type=Path, default=Path("artifacts/reports/orbital_spectra_v9.json"))
    parser.add_argument("--download-missing-masks", action="store_true")
    parser.add_argument("--acquire-public-crism-catalog", action="store_true", help="Acquire small source labels/WV/header files only; no scientific control selected")
    parser.add_argument("--acquire-first-eligible-roi", action="store_true", help="Acquire first date-ordered quality-eligible scene by verified HDF5 HTTPS ranges")
    parser.add_argument("--range-byte-budget-mib", type=int, default=512, help="Maximum transferred bytes per source asset")
    args = parser.parse_args()
    if args.comparison_config:
        characterize_cross_observable(args.comparison_config)
        return
    config = json.loads(args.config.read_text(encoding="utf-8"))
    entries = json.loads(Path(config["seasonal_manifest"]).read_text(encoding="utf-8-sig"))
    root = Path(config["source_root"])
    root.mkdir(parents=True, exist_ok=True)
    quality, bbox = config["quality"], config["roi"]["bbox_wsen"]
    records, requests_manifest = [], []
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=Retry(total=4, backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"], respect_retry_after_header=True)))
    crism_root = Path("data/raw/mars/spectroscopy/crism_mtrdr_preflight")
    crism_base = "https://pds-geosciences.wustl.edu/mro/mro-m-crism-5-rdr-mptargeted-v1/mrocr_4001/"
    example = "mtrdr/2006/2006_273/hrs00002847/"
    catalog_paths = ["bundle_crism_mtrdr.xml"] + [example + f"hrs00002847_07_{suffix}" for suffix in (
        "if173j_mtr3.xml", "if173j_mtr3.hdr", "wv173j_mtr3.xml", "wv173j_mtr3.tab", "in173j_mtr3.xml", "de173l_mtr1.xml")]
    if args.acquire_public_crism_catalog:
        crism_root.mkdir(parents=True, exist_ok=True)
        for relative in catalog_paths:
            local = crism_root / relative.rsplit("/", 1)[-1]
            if not local.exists():
                response = session.get(crism_base + relative, timeout=(30, 60))
                response.raise_for_status()
                local.write_bytes(response.content)
    catalog = []
    crism_wave_summary = None
    ns = {"p": "http://pds.nasa.gov/pds4/pds/v1"}
    for relative in catalog_paths:
        local = crism_root / relative.rsplit("/", 1)[-1]
        if local.exists():
            asset = {"url": crism_base + relative, "path": str(local), "sha256": sha256(local), "bytes": local.stat().st_size}
            if local.suffix == ".xml":
                tree = ET.parse(local)
                asset.update(logical_identifier=tree.findtext(".//p:logical_identifier", namespaces=ns),
                             title=tree.findtext(".//p:Identification_Area/p:title", namespaces=ns),
                             referenced_files=[n.text for n in tree.findall(".//p:File/p:file_name", ns)])
            catalog.append(asset)
    wv_path = crism_root / "hrs00002847_07_wv173j_mtr3.tab"
    wv_label = wv_path.with_suffix(".xml")
    if wv_path.exists() and wv_label.exists():
        wave, widths, good = read_crism_wavelength_table(wv_path, wv_label)
        crism_wave_summary = {"bands": len(wave), "good_bands": int(good.sum()), "wavelength_range_um": [float(wave.min()), float(wave.max())], "fwhm_range_um": [float(widths.min()), float(widths.max())], "quantity": "Source PDS4 WV nanometres converted to micrometres; FWHM only supports a Gaussian response approximation"}
    if args.download_missing_masks or args.acquire_first_eligible_roi:
        token = os.environ.get("EARTHDATA_TOKEN")
        if not token:
            parser.error("EARTHDATA_TOKEN is required for protected acquisition; it is never stored")
        session.headers["Authorization"] = "Bearer " + token
    range_session = requests.Session()
    range_session.headers.update(session.headers)
    range_session.mount("https://", HTTPAdapter(max_retries=Retry(total=1, connect=1, read=0,
        status=1, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"], respect_retry_after_header=False)))
    first_eligible_handled = False
    for entry in entries:
        assets = {}
        for link in entry["links"]:
            url = link["href"]
            filename = url.rsplit("/", 1)[-1]
            if not filename.endswith(".nc") or "data#" not in link["rel"]:
                continue
            kind = "mask" if "_MASK_" in filename else "uncertainty" if "_RFLUNCERT_" in filename else "reflectance"
            path = root / filename
            assets[kind] = {"filename": filename, "url": url, "state": "acquired" if path.exists() else "missing"}
            if kind == "mask" and not path.exists() and args.download_missing_masks:
                # A partial is resumed only when the server confirms its exact offset.
                part = path.with_suffix(path.suffix + ".part")
                offset = part.stat().st_size if part.exists() else 0
                response = session.get(url, headers={"Range": f"bytes={offset}-"} if offset else {}, stream=True, timeout=(30, 120))
                response.raise_for_status()
                append = offset > 0 and response.status_code == 206
                if append and not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                    raise ValueError("Server returned a different byte range than requested")
                with part.open("ab" if append else "wb") as stream:
                    for chunk in response.iter_content(1024 * 1024):
                        stream.write(chunk)
                with Dataset(part):
                    pass
                part.replace(path)
                assets[kind]["state"] = "acquired"
            if path.exists():
                assets[kind].update(bytes=path.stat().st_size, sha256=sha256(path))
        record = {"granule_id": entry["title"], "cmr_id": entry["id"], "time_start": entry["time_start"], "assets": assets}
        mask_path = root / assets["mask"]["filename"]
        if mask_path.exists():
            mask = EmitMask.read(mask_path)
            record["roi_quality"] = mask.inventory(bbox, quality["required_zero_flags"])
            record["analysis_state"] = "no_quality_eligible_centers" if record["roi_quality"]["native_clear_centers"] == 0 else "reflectance_and_uncertainty_missing"
            rectangle = record["roi_quality"]["native_rectangle_inclusive"]
            derived_path = root / "derived_roi" / (entry["title"] + "_derived_native_roi.nc")
            if record["roi_quality"]["native_clear_centers"] and not first_eligible_handled:
                first_eligible_handled = True
                if args.acquire_first_eligible_roi and not derived_path.exists():
                    acquire_emit_rectangle(assets["reflectance"]["url"], assets["uncertainty"]["url"], rectangle, range_session, derived_path, args.range_byte_budget_mib * 1024 * 1024)
            if derived_path.exists():
                spectra = read_derived_emit_roi(derived_path, mask, bbox, quality["required_zero_flags"], quality["masked_intervals_um"])
                record["derived_roi_asset"] = {"path": str(derived_path), "sha256": sha256(derived_path), "bytes": derived_path.stat().st_size, "role": "derived_rectangle_not_full_source_cube"}
                with Dataset(derived_path) as derived:
                    record["derived_roi_asset"]["source_range_acquisition"] = json.loads(derived.source_metadata_json)
                record["spectral_summary"] = spectra.descriptive_summary()
                figure_path = args.output.with_suffix(".png")
                save_spectral_figure(spectra, quality["masked_intervals_um"], figure_path)
                record["spectral_figure"] = {"path": str(figure_path), "sha256": sha256(figure_path), "source_derived_roi_sha256": record["derived_roi_asset"]["sha256"]}
                record["analysis_state"] = "descriptive_native_roi_spectra_only"
                record["diagnostics"] = {d["id"]: diagnostic_availability(spectra.wavelength_um, spectra.valid, d["interval_um"], quality["masked_intervals_um"]) for d in config["diagnostics"]}
            if all(assets[k]["state"] == "acquired" for k in ("reflectance", "uncertainty")) and record["roi_quality"]["native_clear_centers"]:
                spectra = read_emit_roi(root / assets["reflectance"]["filename"], root / assets["uncertainty"]["filename"], mask, bbox, quality["required_zero_flags"], quality["masked_intervals_um"])
                record["spectral_summary"] = spectra.descriptive_summary()
                record["analysis_state"] = "descriptive_native_roi_spectra_only"
                record["diagnostics"] = {d["id"]: diagnostic_availability(spectra.wavelength_um, spectra.valid, d["interval_um"], quality["masked_intervals_um"]) for d in config["diagnostics"]}
            if rectangle is not None:
                r0, r1, c0, c1 = rectangle
                requests_manifest.append({"granule_id": entry["title"], "native_rectangle_inclusive": rectangle,
                    "estimated_float32_bytes_per_cube_rectangle_285_bands": (r1-r0+1)*(c1-c0+1)*285*4,
                    "opendap_catalogued_service": next((l["href"] for l in entry["links"] if "OPeNDAP" in l.get("title", "")), None),
                    "subset_state": "Service catalogued; authenticated DMR variable paths and successful response not yet verified. Do not treat this as an acquired subset.",
                    "reflectance_projection_dap2_candidate": f"reflectance[{r0}:1:{r1}][{c0}:1:{c1}][0:1:284]",
                    "uncertainty_projection_dap2_candidate": f"reflectance_uncertainty[{r0}:1:{r1}][{c0}:1:{c1}][0:1:284]",
                    "required_metadata": ["sensor_band_parameters/wavelengths", "sensor_band_parameters/fwhm", "location/lat", "location/lon", "geotransform", "source native rectangle offsets"],
                    "missing_asset_requests": [assets[k] for k in ("reflectance", "uncertainty") if assets[k]["state"] == "missing"]})
        else:
            record["analysis_state"] = "mask_missing"
        records.append(record)
    acquired = [r for r in records if "roi_quality" in r]
    usable = [r for r in acquired if r["roi_quality"]["native_clear_centers"] > 0]
    result = {"schema_version": 1, "experiment_id": config["experiment_id"], "generated_utc": datetime.now(timezone.utc).isoformat(),
        "config_sha256": sha256(args.config), "seasonal_manifest_sha256": sha256(Path(config["seasonal_manifest"])),
        "implementation_sha256": {str(p): sha256(p) for p in (Path(__file__), Path("src/orbital_spectra.py"))},
        "claim_ceiling": config["claim_ceiling"], "roi": config["roi"],
        "summary": {"expected_seasonal_granules": len(entries), "acquired_masks": len(acquired), "missing_masks": len(entries)-len(acquired), "scenes_with_quality_eligible_native_centers": len(usable),
                    "scenes_with_reflectance_and_uncertainty_analysis": sum("spectral_summary" in r for r in records),
                    "analysis_state": "orbital_validation_abstains_without_independent_registered_geological_controls",
                    "roi_area_state": "not_estimated_native_center_counts_are_not_area",
                    "independent_geological_positive_negative_pairs": 0},
        "limitations": ["Review bbox has not been registered to archived specimens", "No independently documented matched negative geological zone is available", "July-October acquisition does not establish snow-free ground", "Channel uncertainty does not provide spatial or continuum covariance", "1900 diagnostic must abstain under the fixed 1.80-1.96 um atmospheric mask", "No phase identification, classification accuracy, AUC or new-site claim is supported"],
        "quality_policy": quality, "sources": config["sources"], "granules": records,
        "crism": {"state": "no_registered_geological_control_cube_acquired", "verified_product_contract": "MTRDR IF is corrected I/F; WV supplies wavelengths, IN processing information and DE geometry. SU/SR summary products are not reflectance cubes. PDS4 bundle exists; exact geological control IDs remain unselected.", "pds4_bundle": config["sources"][-1], "acquired_catalog_assets": catalog, "actual_wv_table_summary": crism_wave_summary, "catalog_example_role": "First archive directory inspected only to verify product contracts; hrs00002847 is not a selected mineral positive or negative control"},
        "acquisition_requests": requests_manifest}
    result["record_hash"] = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    lines = ["# Orbital spectroscopy v9", "",
        f"{len(acquired)}/{len(entries)} seasonal EMIT masks are acquired; {len(usable)} scenes have native centers passing all required zero flags within the provisional bbox. "
        f"{result['summary']['scenes_with_reflectance_and_uncertainty_analysis']} scenes have actual reflectance and uncertainty analysis. Geological orbital validation abstains because the bbox and matched negative zones lack independent specimen registration.", "",
        "| Acquisition | Native ROI centers | Quality-eligible native centers | Analysis |",
        "|---|---:|---:|---|"]
    for record in records:
        roi = record.get("roi_quality", {})
        lines.append(f"| {record['time_start']} | {roi.get('native_roi_centers', 'missing')} | {roi.get('native_clear_centers', 'missing')} | {record['analysis_state']} |")
    lines.extend(["", "Native center counts and repeated GLT cells are neither area estimates nor independent geological replicates. July-October acquisition and zero flags do not establish snow-free material.", "",
        "The fixed 1.80-1.96 micrometre mask excludes the 1.90 micrometre diagnostic. Supplied per-pixel channel posterior standard deviations do not establish uncertainty of continuum removal or a geological mean without covariance information. FWHM permits Gaussian response approximation, not exact measured response convolution.", "",
        f"{len(catalog)} small public CRISM source assets have been acquired. The inspected hrs00002847 directory is a product-contract example with no assigned positive or negative geological label. Its reflectance image cube has not been acquired.", "",
        "The JSON preserves all expected asset contracts, source URLs, acquired asset hashes, native subset rectangles, missing requests, byte-range ancestry for derived ROIs, and implementation hashes. Full source hashes are unavailable for range subsets; derived ROI hashes are explicit.", "",
        "Record hash: " + result["record_hash"], "", "## Primary sources", ""])
    lines.extend("- " + source for source in config["sources"])
    args.output.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))


def characterize_cross_observable(config_path):
    config = json.loads(config_path.read_text(encoding="utf-8"))
    baseline_path = Path(config["baseline_report"])
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    policy = json.loads(Path(config["baseline_config"]).read_text(encoding="utf-8"))
    acquired = [g for g in baseline["granules"] if "derived_roi_asset" in g]
    if len(acquired) != 1:
        raise ValueError("V10 follow-up requires exactly the one acquired V9 scene")
    granule = acquired[0]
    derived_path = Path(granule["derived_roi_asset"]["path"])
    if sha256(derived_path) != granule["derived_roi_asset"]["sha256"]:
        raise ValueError("Derived source differs from preserved V9 lineage")
    mask_path = Path(policy["source_root"]) / granule["assets"]["mask"]["filename"]
    mask = EmitMask.read(mask_path)
    quality, bbox = policy["quality"], policy["roi"]["bbox_wsen"]
    orbital = read_derived_emit_roi(derived_path, mask, bbox, quality["required_zero_flags"], quality["masked_intervals_um"])
    feature = config["feature"]
    required = np.logical_or.reduce([(orbital.wavelength_um >= lo) & (orbital.wavelength_um <= hi)
        for lo, hi in (feature["left_shoulder_um"], feature["search_um"], feature["right_shoulder_um"])])
    cohort = orbital.valid[:, required].all(axis=1)
    if not cohort.any():
        raise ValueError("No complete native centers on frozen V10 feature support")
    mean = Spectrum(orbital.wavelength_um, orbital.reflectance[cohort].mean(axis=0),
                    orbital.valid[cohort].all(axis=0), orbital.source_id + ":complete-feature-cohort-mean")
    mean_feature = fixed_continuum_feature(mean, feature)
    native_rows, native_cols = np.nonzero(roi_centers(mask.lon, mask.lat, bbox) & mask.clear(quality["required_zero_flags"]))
    pixels = []
    for i, (values, valid) in enumerate(zip(orbital.reflectance, orbital.valid)):
        spectrum = Spectrum(orbital.wavelength_um, values, valid, orbital.source_id + f":native-center-{i}")
        pixels.append({"index": i, "native_row": int(native_rows[i]), "native_col": int(native_cols[i]),
                       "feature": fixed_continuum_feature(spectrum, feature)})
    protocol = ControlProtocol.read(Path(config["archive_protocol"]))
    measurements, archive_lineage = read_archive(Path("."), protocol)
    references, matched_spectra = [], []
    for measurement in measurements:
        source = measurement.reflectance_spectrum()
        if source is None:
            continue
        matched = reference_emit_approximation(source, orbital.wavelength_um, orbital.fwhm_um,
            quality["masked_intervals_um"], config["response"]["minimum_gaussian_mass_inside_native_axis"])
        result = fixed_continuum_feature(matched, feature)
        references.append({"sample_id": measurement.spec.sample_id, "kind": measurement.spec.kind,
            "source_id": source.source_id, "native_axis_unit": measurement.axis_unit,
            "native_ordinate_unit": measurement.ordinate_unit, "feature": result,
            "unavailable_response_channels_um": matched.wavelength_um[~matched.valid].tolist(),
            "comparison_with_roi_mean": compare_fixed_features(mean_feature, result),
            "comparisons_with_all_native_centers": [{"native_center_index": p["index"], **compare_fixed_features(p["feature"], result)} for p in pixels]})
        matched_spectra.append(matched)
    depths = np.asarray([p["feature"]["depth"] for p in pixels if p["feature"]["depth"] is not None])
    output = Path(config["output"])
    output.parent.mkdir(parents=True, exist_ok=True)
    figure = output.with_suffix(".png")
    save_cross_observable_figure(orbital, mean, pixels, references, matched_spectra, figure)
    result = {"schema_version": 1, "experiment_id": config["experiment_id"], "claim_ceiling": config["claim_ceiling"],
        "generated_utc": datetime.now(timezone.utc).isoformat(), "config": config,
        "config_sha256": sha256(config_path), "baseline_report_sha256": sha256(baseline_path),
        "baseline_record_hash": baseline["record_hash"], "derived_roi_sha256": sha256(derived_path),
        "implementation_sha256": {str(p): sha256(p) for p in (Path(__file__), Path("src/orbital_spectra.py"), Path("src/spectra.py"), Path("src/laboratory.py"))},
        "summary": {"field_references": sum(r["kind"] == "field_vnir" for r in references),
                    "lab_references": sum(r["kind"] == "lab_vnir" for r in references),
                    "native_centers": len(pixels), "complete_feature_native_centers": int(cohort.sum()),
                    "roi_mean_feature": mean_feature, "individual_center_depth_min_median_max": [float(x) for x in (depths.min(), np.median(depths), depths.max())] if len(depths) else None,
                    "reference_feature_abstentions": sum(r["feature"]["depth"] is None for r in references),
                    "interpretation": "A measured continuum-relative depression and all specimen differences; no specimen-to-orbit registration, phase identification, accuracy, abundance or significance"},
        "orbital_feature_channels_um": orbital.wavelength_um[required].tolist(), "native_centers": pixels,
        "references": references, "archive_lineage": archive_lineage,
        "figure": {"path": str(figure), "sha256": sha256(figure)},
        "caveats": ["Archive relative reflectance uses Spectralon and lamp/contact-probe geometry; orbital atmospherically corrected surface reflectance has different illumination/view geometry and footprints", "EMIT pixels mix materials and may include soil, moisture, vegetation or shadow; center quality flags do not establish a pure geological unit", config["response"]["native_resolution_caveat"], "No conversion of FTIR or XRD amplitudes into reflectance; archived XRD is not independently assigned to the orbital footprint", "Depth is a sampled engineering continuum ratio, not mineral abundance. Supplied channel SD lacks covariance for a depth confidence interval", "Every archived VNIR specimen and every retained ROI center is reported; incomplete fixed support abstains rather than changing metric support"],
        "additional_geological_controls": {"state": "not_acquired_or_registered", "minimum_scope": "Three independently mapped material roles, not a statistically powered sample-size claim",
            "roles": ["A hydrothermal deposit polygon independently linked to field specimens and compositional/XRD observations, with georegistration and pixel-scale material fractions", "A local unaltered substrate/valley-fill control independently selected from geological mapping and field chemistry, matched for illumination, grain size, moisture and cover, without selection by this spectral feature", "A difficult independently confirmed Al-OH/clay or other hydrated-material confounder with a 2.2 um feature, selected from mineralogy rather than the EMIT absorption map"],
            "source_basis": "Sarkar et al. 2022 documents separate valley-fill borate and sulfur-associated sulfate settings; Sarkar et al. LPSC2023 1464 Figure1 supplies geological context, and its VNIR/XRD discrepancies show why independent composition is required. A regional map alone does not register these EMIT centers.",
            "minimum_new_observations": "Recover georeferenced field/sample coordinates and mapped contacts, verify footprint mixtures with finer imagery/field mapping, obtain matched VNIR plus independent XRD/composition for each role; require spatial repeats for generalization but no universal numerical sample-size minimum is claimed", "coordinates": None,
            "band_limits": "Retain multiple independent diagnostic features outside fixed exclusions; masked 1.4/1.9 um evidence cannot be recovered by this comparison"}}
    result["record_hash"] = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    write_cross_observable_markdown(result, output.with_suffix(".md"))
    print(json.dumps(result["summary"], indent=2))


def save_cross_observable_figure(orbital, mean, pixels, references, matched_spectra, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(12, 9), layout="constrained")
    wave = orbital.wavelength_um
    selection = (wave >= 2.08) & (wave <= 2.46)
    for values, valid in zip(orbital.reflectance, orbital.valid):
        axes[0].plot(wave[selection], np.where(valid, values, np.nan)[selection], color=".7", alpha=.25, linewidth=.5)
    for ref, spectrum in zip(references, matched_spectra):
        color = "#367c9e" if ref["kind"] == "field_vnir" else "#b77835"
        axes[0].plot(wave[selection], np.where(spectrum.valid, spectrum.reflectance, np.nan)[selection], color=color, alpha=.45, linewidth=.8)
    axes[0].plot(wave[selection], np.where(mean.valid, mean.reflectance, np.nan)[selection], color="black", linewidth=2, label="EMIT complete-feature-cohort mean")
    axes[0].plot([], [], color="#367c9e", label="All 14 field archive spectra, Gaussian approximation")
    axes[0].plot([], [], color="#b77835", label="All 10 laboratory archive spectra, Gaussian approximation")
    axes[0].axvspan(2.18, 2.23, color="#b3caba", alpha=.3, label="Fixed diagnostic search")
    axes[0].set(xlabel="Wavelength (micrometres)", ylabel="Reflectance (different observation geometries)")
    axes[0].legend(fontsize=8, frameon=False)
    pixel_depths = [p["feature"]["depth"] for p in pixels if p["feature"]["depth"] is not None]
    if pixel_depths:
        axes[1].axhspan(min(pixel_depths), max(pixel_depths), color=".85", label="Full range across eligible native centers; not a confidence interval")
    mean_depth = fixed_continuum_feature(mean, {"id": "fixed_2200", "left_shoulder_um": [2.1, 2.14], "search_um": [2.18, 2.23], "right_shoulder_um": [2.4, 2.44], "minimum_channels_per_region": 2})["depth"]
    if mean_depth is not None:
        axes[1].axhline(mean_depth, color="black", label="Depth of ROI mean")
    for i, ref in enumerate(references):
        depth = ref["feature"]["depth"]
        if depth is not None:
            axes[1].scatter(i, depth, color="#367c9e" if ref["kind"] == "field_vnir" else "#b77835", s=25)
    axes[1].set_xticks(range(len(references)), [r["sample_id"] + (" F" if r["kind"] == "field_vnir" else " L") for r in references], rotation=70, ha="right", fontsize=7)
    axes[1].set_ylabel("Fixed continuum-relative apparent depth")
    axes[1].legend(fontsize=8, frameon=False)
    fig.suptitle("Puga: exploratory cross-observable characterization, all specimens retained")
    fig.supxlabel("Unregistered site/specimen footprints; mixtures and geometry differ. No phase identity, ranking accuracy or significance.", fontsize=9)
    fig.savefig(path, dpi=180)
    plt.close(fig)


def write_cross_observable_markdown(result, path):
    summary = result["summary"]
    feature = summary["roi_mean_feature"]
    lines = ["# Exploratory orbital spectroscopy v10", "",
        f"The fixed ROI mean diagnostic has apparent depth {feature['depth']:.5f} at sampled wavelength {feature['sampled_minimum_um']:.6f} micrometres. All {summary['complete_feature_native_centers']} of {summary['native_centers']} quality-eligible native centers retain every fixed diagnostic channel. This characterizes an absorption; specimen registration and mineral identity remain unresolved.", "",
        "The support reuses V6 shoulders at 2.10-2.14 and 2.40-2.44 micrometres and V9 search at 2.18-2.23 micrometres. The V9 absorption plot and channel availability were inspected before this separately versioned follow-up. No continuum interval was optimized against the new depth outcomes.", "",
        "| Archive specimen | Kind | Apparent depth | Difference, ROI mean minus archive |", "|---|---|---:|---:|"]
    for ref in result["references"]:
        depth, delta = ref["feature"]["depth"], ref["comparison_with_roi_mean"]["depth_difference"]
        lines.append(f"| {ref['sample_id']} | {ref['kind']} | {depth if depth is not None else 'abstain'} | {delta if delta is not None else 'abstain'} |")
    lines += ["", "Every field and laboratory spectrum and every eligible native center is retained in the JSON, including all unavailable-channel outcomes. Gaussian FWHM smoothing is an approximation applied to already resolved FieldSpec measurements; no measured EMIT or FieldSpec response deconvolution is available.", ""]
    lines += result["caveats"]
    lines += ["", "## Additional geological controls", "", "The minimum discriminatory design needs three independently established material roles. This is a design requirement, not an asserted statistical sample size.", ""]
    lines += ["- " + role for role in result["additional_geological_controls"]["roles"]]
    lines += ["", result["additional_geological_controls"]["source_basis"], "", result["additional_geological_controls"]["minimum_new_observations"], "", "No new control coordinates or mineral labels were inferred from the band map. The fixed atmospheric exclusions continue to remove the 1.4 and 1.9 micrometre evidence.", "", "## Primary sources", ""]
    lines += ["- " + source for source in result["config"]["sources"]]
    lines += ["", "Record hash: " + result["record_hash"]]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
