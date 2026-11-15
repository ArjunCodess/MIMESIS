"""Run the frozen Puga known-control characterization from verified originals."""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from src.laboratory import characterize_archive, file_lineage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=Path("data/derived/puga_control_v6"))
    args = parser.parse_args()
    root = args.root.resolve()
    output = root / args.output
    output.mkdir(parents=True, exist_ok=True)
    result = characterize_archive(root, root / "configs/puga_control_v6.json")
    result["lineage"]["runner"] = file_lineage(Path(__file__).resolve(), root)
    (output / "puga_control_v6.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    public_path = root / "apps/web/public/research/puga_control_v6.json"
    public_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    summary = result["summary"]
    pairs = result["matched_pairs"]
    ids = [p["sample_id"] for p in pairs]
    all_pairs = pairs + result["mismatch_pairs"]
    matrix = np.array([[next(c["spectral_angle_radians"] for c in all_pairs
                       if c["field_sample_id"] == a and c["lab_sample_id"] == b)
                       for b in ids] for a in ids])
    fig, ax = plt.subplots(figsize=(10, 8), layout="constrained")
    heat = ax.imshow(matrix, cmap="viridis", vmin=0)
    ax.set_xticks(range(len(ids)), ids, rotation=55, ha="right", fontsize=8)
    ax.set_yticks(range(len(ids)), ids, fontsize=8)
    ax.set(xlabel="Laboratory archive specimen", ylabel="Field archive specimen",
           title="Puga field/lab spectral angle on common 20 nm boxes")
    for i in range(len(ids)):
        for j in range(len(ids)):
            ax.text(j, i, f"{matrix[i, j]:.3f}", ha="center", va="center",
                    fontsize=7, color="white" if matrix[i, j] < matrix.max() * .55 else "black")
    fig.colorbar(heat, ax=ax, label="Spectral angle, radians; smaller is closer")
    fig.savefig(output / "puga_sam_matrix.png", dpi=180)
    plt.close(fig)
    lines = [
        "# Puga known-control characterization", "",
        f"The archive supplies {summary['paired_sample_count']} filename-linked field/laboratory VNIR specimen pairs. "
        f"The same-ID laboratory spectrum is nearest by spectral angle for {summary['same_sample_nearest_by_sam_count']} "
        f"of {summary['paired_sample_count']} field spectra, and nearest by continuum-relative RMSE for "
        f"{summary['same_sample_nearest_by_continuum_rmse_count']}. These are descriptive archive comparisons, not mineral identifications.",
        "", "## Measurements and comparison", "",
        "All 41 original files pass their Zenodo manifest MD5 and byte-count checks. The inputs contain 14 field VNIR, "
        "10 laboratory VNIR, 9 FTIR and 8 XRD exports. Ten shared specimen IDs produce 10 matched pairs and 90 "
        "different-ID comparisons. Four field spectra have no laboratory partner and are inventoried without entering the comparison matrix.",
        "", "The frozen protocol integrates each VNIR spectrum over 105 common 20 nm boxes from 0.4 to 2.5 micrometres. "
        "Only fully supported, positive finite native segments are usable. This is an explicit analysis response, not a measured "
        "EMIT, CRISM or FieldSpec response. SAM compares overall spectral direction, reflectance RMSE retains amplitude differences, "
        "and continuum RMSE compares the three declared broad absorption windows.",
        "", "| Metric | Matched median | Different-ID median |", "|---|---:|---:|",
    ]
    for metric in ("spectral_angle_radians", "reflectance_rmse", "continuum_removed_rmse"):
        lines.append(f"| {metric} | {summary['matched'][metric]['median']:.6f} | {summary['mismatch'][metric]['median']:.6f} |")
    lines.extend(["", "| Specimen | Common bins | SAM, radians | Reflectance RMSE | Continuum RMSE | SAM rank | Shape rank |",
                  "|---|---:|---:|---:|---:|---:|---:|"])
    for pair in pairs:
        lines.append(f"| {pair['sample_id']} | {pair['common_bins']} | {pair['spectral_angle_radians']:.6f} | "
                     f"{pair['reflectance_rmse']:.6f} | {pair['continuum_removed_rmse']:.6f} | "
                     f"{pair['ranks']['spectral_angle_radians']['best_rank']} | "
                     f"{pair['ranks']['continuum_removed_rmse']['best_rank']} |")
    lines.extend(["", "Ranks are within the ten laboratory candidates for each field spectrum. JSON preserves both ends of tied ranks. "
                  "Different-ID controls can share mineral assemblages, and each spectrum occurs in several pairs, so these comparisons "
                  "do not estimate independent accuracy or significance.", "", "![All paired spectral angles](puga_sam_matrix.png)",
                  "", "## Sources and limits", "",
                  "[Sarkar et al., 2022](https://doi.org/10.1029/2022JE007299) already studies Puga as a Martian analogue. "
                  "The original data are [Zenodo 3992541](https://doi.org/10.5281/zenodo.3992541) and "
                  "[Zenodo 6304000](https://doi.org/10.5281/zenodo.6304000), both CC BY 4.0. The JSON includes their "
                  "creator metadata, archive checksums and local SHA-256 hashes, plus hashes of the frozen protocol and implementation.", ""])
    lines.extend(f"- {limit}" for limit in result["limitations"])
    lines.extend(["", "Reproduce with `python scripts/characterize_puga.py`. The machine-readable output preserves native "
                  "measurement summaries, the complete comparison matrix, per-window diagnostics and explicit null uncertainty estimates. "
                  "The 20 nm grid quantizes sampled minima; it is not a calibrated wavelength uncertainty.", ""])
    (output / "puga_control_v6.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
