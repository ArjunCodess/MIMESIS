"""Native, source-linked sample spectroscopy without invented mineral labels.

The archive's VNIR axis is nanometres according to the associated study. FTIR
and XRD stay in their own native domains; they never become reflectance vectors.
"""

from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
from typing import Literal

import numpy as np

from src.spectra import Spectrum, spectral_angle


MeasurementKind = Literal["field_vnir", "lab_vnir", "ftir", "xrd"]


@dataclass(frozen=True)
class AssetSpec:
    record_id: str
    kind: MeasurementKind
    sample_id: str
    filename: str

    def __post_init__(self):
        if self.kind not in {"field_vnir", "lab_vnir", "ftir", "xrd"}:
            raise ValueError("Unknown measurement kind")
        if not all(isinstance(x, str) and x for x in (
            self.record_id, self.sample_id, self.filename
        )):
            raise ValueError("Record, specimen and filename must be nonempty strings")
        if Path(self.filename).name != self.filename or self.filename in {".", ".."}:
            raise ValueError("Archive filenames cannot contain path components")

    @property
    def is_vnir(self) -> bool:
        return self.kind in {"field_vnir", "lab_vnir"}

    @property
    def source_id(self) -> str:
        return f"zenodo:{self.record_id}:{self.filename}"


@dataclass(frozen=True)
class AbsorptionWindow:
    id: str
    left_shoulder_um: tuple[float, float]
    search_um: tuple[float, float]
    right_shoulder_um: tuple[float, float]

    def __post_init__(self):
        bounds = (*self.left_shoulder_um, *self.search_um, *self.right_shoulder_um)
        if len(bounds) != 6 or not np.isfinite(bounds).all():
            raise ValueError("Six finite continuum/search bounds are required")
        if not all(a < b for a, b in zip(bounds, bounds[1:])):
            raise ValueError("Continuum shoulders must bracket the distinct search interval")


@dataclass(frozen=True)
class ControlProtocol:
    assets: tuple[AssetSpec, ...]
    windows: tuple[AbsorptionWindow, ...]
    support_um: tuple[float, float]
    box_width_um: float
    max_native_gap_um: float
    minimum_common_bins: int
    payload: dict

    @classmethod
    def read(cls, path: Path) -> "ControlProtocol":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload["schema_version"] != 1:
            raise ValueError("Unsupported Puga protocol schema")
        assets = tuple(AssetSpec(**item) for item in payload["assets"])
        keys = [(a.record_id, a.filename) for a in assets]
        specimens = [(a.kind, a.sample_id) for a in assets]
        if len(set(keys)) != len(keys) or len(set(specimens)) != len(specimens):
            raise ValueError("An asset or a specimen/measurement pair occurs twice")
        windows = tuple(AbsorptionWindow(
            item["id"], tuple(item["left_shoulder_um"]), tuple(item["search_um"]),
            tuple(item["right_shoulder_um"])
        ) for item in payload["absorption_windows"])
        if not windows or len({w.id for w in windows}) != len(windows):
            raise ValueError("Unique absorption-window names are required")
        transform = payload["transform"]
        support = tuple(transform["common_support_um"])
        width, gap = transform["box_width_um"], transform["max_native_gap_um"]
        minimum = payload["outcomes"]["minimum_common_bins"]
        if len(support) != 2 or not np.isfinite((*support, width, gap)).all():
            raise ValueError("Finite common support, width and gap are required")
        if support[0] <= 0 or support[1] <= support[0] or width <= 0 or gap <= 0:
            raise ValueError("Positive ordered support, bin width and native gap are required")
        bins = (support[1] - support[0]) / width
        if not np.isclose(bins, round(bins)) or not isinstance(minimum, int) or minimum < 3:
            raise ValueError("Support must divide into full bins, with at least three required")
        if any(w.left_shoulder_um[0] < support[0] or
               w.right_shoulder_um[1] > support[1] for w in windows):
            raise ValueError("Continuum windows must stay inside common support")
        return cls(assets, windows, support, width, gap, minimum, payload)

    @property
    def edges_um(self) -> np.ndarray:
        count = round((self.support_um[1] - self.support_um[0]) / self.box_width_um)
        return np.linspace(*self.support_um, count + 1)


@dataclass(frozen=True)
class NativeMeasurement:
    spec: AssetSpec
    axis: np.ndarray
    values: np.ndarray
    axis_unit: str
    ordinate_unit: str
    header: tuple[str, ...] = ()

    def __post_init__(self):
        if (self.axis.ndim != 1 or len(self.axis) < 3 or
                not np.isfinite(self.axis).all() or np.any(np.diff(self.axis) <= 0)):
            raise ValueError("Native axis must be finite and strictly increasing")
        if self.values.shape != self.axis.shape:
            raise ValueError("One native ordinate is required per axis coordinate")
        self.axis.setflags(write=False)
        self.values.setflags(write=False)

    def reflectance_spectrum(self) -> Spectrum | None:
        """Only explicitly established VNIR nanometres/reflectance can convert."""
        if (not self.spec.is_vnir or self.axis_unit != "nm" or
                self.ordinate_unit != "relative_reflectance"):
            return None
        valid = np.isfinite(self.values) & (self.values > 0)
        return Spectrum(self.axis / 1000.0, self.values, valid, self.spec.source_id)

    def summary(self) -> dict:
        finite = self.values[np.isfinite(self.values)]
        return {
            "sample_id": self.spec.sample_id, "kind": self.spec.kind,
            "source_id": self.spec.source_id, "filename": self.spec.filename,
            "rows": len(self.axis), "axis_unit": self.axis_unit,
            "axis_min": float(self.axis[0]), "axis_max": float(self.axis[-1]),
            "native_step_median": float(np.median(np.diff(self.axis))),
            "ordinate_unit": self.ordinate_unit,
            "ordinate_min": float(finite.min()) if finite.size else None,
            "ordinate_max": float(finite.max()) if finite.size else None,
            "nonfinite_ordinates": int((~np.isfinite(self.values)).sum()),
            "nonpositive_ordinates": int((self.values <= 0).sum()),
            "ordinates_above_one": int((self.values > 1).sum()),
            "native_header": list(self.header),
            "state": ("known_control_characterization" if self.reflectance_spectrum()
                      is not None else "unit_abstention" if self.spec.kind == "ftir"
                      or self.spec.is_vnir else "native_evidence_only"),
            "mineral_assignment": None,
        }


def read_measurement(path: Path, spec: AssetSpec, units: dict) -> NativeMeasurement:
    """Parse a declared native format; infer neither units nor specimen identity."""
    text = path.read_text(encoding="utf-8-sig")
    header: tuple[str, ...] = ()
    if spec.kind == "xrd":
        lines = text.splitlines()
        if not lines or lines[0].strip() != ";RAW4.00" or "[Data]" not in lines:
            raise ValueError(f"Expected RAW4 XRD header: {spec.filename}")
        start = lines.index("[Data]")
        if [p.strip() for p in lines[start + 1].split(",")] != ["Angle", "PSD", ""]:
            raise ValueError("Expected native XRD Angle/PSD columns")
        header = tuple(lines[:start + 2])
        data = np.loadtxt(io.StringIO("\n".join(lines[start + 2:])),
                          delimiter=",", usecols=(0, 1), ndmin=2)
        counts = [int(line.split("=", 1)[1]) for line in header
                  if line.startswith("NumberOfMeasuredData=")]
        if len(counts) != 1 or counts[0] != len(data):
            raise ValueError("XRD declared and observed row counts differ")
    else:
        data = np.loadtxt(io.StringIO(text), delimiter="," if spec.kind == "ftir"
                          else None, ndmin=2)
    if data.shape[1] != 2:
        raise ValueError(f"Exactly two native columns are required: {spec.filename}")
    return NativeMeasurement(spec, data[:, 0], data[:, 1],
                             units["axis"], units["ordinate"], header)


def file_lineage(path: Path, root: Path, expected_md5: str | None = None) -> dict:
    content = path.read_bytes()
    md5 = hashlib.md5(content).hexdigest()
    if expected_md5 is not None and md5 != expected_md5:
        raise ValueError(f"Source MD5 mismatch for {path.name}")
    return {
        "path": path.relative_to(root).as_posix(), "bytes": len(content),
        "md5": md5, "sha256": hashlib.sha256(content).hexdigest(),
        "expected_md5": expected_md5,
        "archive_md5_verified": expected_md5 is not None,
    }


def read_archive(root: Path, protocol: ControlProtocol) -> tuple[list[NativeMeasurement], list[dict]]:
    """Validate record manifests and hashes before parsing their measurements."""
    source_root = root / protocol.payload["source_root"]
    measurements, records = [], []
    for expected in protocol.payload["records"]:
        record_path = source_root / expected["id"] / "record.json"
        raw = json.loads(record_path.read_text(encoding="utf-8"))
        metadata = raw["metadata"]
        if str(raw["id"]) != expected["id"] or metadata["doi"] != expected["doi"]:
            raise ValueError("Unexpected Zenodo record identity")
        if metadata["license"]["id"] != expected["license_id"]:
            raise ValueError("Archive license differs from frozen protocol")
        manifest = {item["key"]: item for item in raw["files"]}
        assets = [a for a in protocol.assets if a.record_id == expected["id"]]
        if (len(manifest) != len(raw["files"]) or
                len(manifest) != expected["expected_file_count"] or
                set(manifest) != {a.filename for a in assets}):
            raise ValueError("Frozen asset list must exactly cover the record manifest")
        files = []
        for spec in assets:
            item = manifest[spec.filename]
            algorithm, checksum = item["checksum"].split(":", 1)
            if algorithm != "md5" or len(checksum) != 32:
                raise ValueError("Expected Zenodo MD5 checksum")
            path = record_path.parent / spec.filename
            lineage = file_lineage(path, root, checksum)
            if lineage["bytes"] != item["size"]:
                raise ValueError("Archive size differs from source manifest")
            lineage.update({
                "source_id": spec.source_id, "sample_id": spec.sample_id,
                "kind": spec.kind, "download_url": item["links"]["self"],
            })
            files.append(lineage)
            family = "vnir" if spec.is_vnir else spec.kind
            measurements.append(read_measurement(path, spec,
                protocol.payload["measurement_units"][family]))
        records.append({
            "record_id": expected["id"], "doi": metadata["doi"],
            "url": f"https://zenodo.org/records/{expected['id']}",
            "title": metadata["title"], "publication_date": metadata["publication_date"],
            "license_id": metadata["license"]["id"],
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "creators": metadata["creators"],
            "record_metadata": file_lineage(record_path, root), "files": files,
        })
    known_ids = {record["record_id"] for record in records}
    if any(asset.record_id not in known_ids for asset in protocol.assets):
        raise ValueError("An asset references an undeclared archive record")
    return measurements, records


def box_average(source: Spectrum, edges_um: np.ndarray, max_native_gap_um: float) -> Spectrum:
    """Integrate a common box response without bridging native invalid samples."""
    if (edges_um.ndim != 1 or len(edges_um) < 4 or
            not np.isfinite(edges_um).all() or np.any(np.diff(edges_um) <= 0)):
        raise ValueError("At least three bins with finite increasing edges are required")
    if not np.isfinite(max_native_gap_um) or max_native_gap_um <= 0:
        raise ValueError("A positive finite maximum native gap is required")
    wave = source.wavelength_um
    centers = (edges_um[:-1] + edges_um[1:]) / 2
    values = np.full(len(centers), np.nan)
    valid = np.zeros(len(centers), dtype=bool)
    for i, (lo, hi) in enumerate(zip(edges_um[:-1], edges_um[1:])):
        if lo < wave[0] - 1e-12 or hi > wave[-1] + 1e-12:
            continue
        lo, hi = max(lo, wave[0]), min(hi, wave[-1])
        first = max(0, int(np.searchsorted(wave, lo, side="right")) - 1)
        stop = min(len(wave), int(np.searchsorted(wave, hi, side="left")) + 1)
        native = slice(first, stop)
        if (not source.valid[native].all() or
                np.any(np.diff(wave[native]) > max_native_gap_um + 1e-12)):
            continue
        interior = wave[(wave > lo) & (wave < hi)]
        coordinates = np.r_[lo, interior, hi]
        ordinates = np.interp(coordinates, wave[native], source.reflectance[native])
        values[i] = float(np.trapezoid(ordinates, coordinates) / (hi - lo))
        valid[i] = True
    return Spectrum(centers, values, valid, source.source_id + ":common-box-average")


@dataclass(frozen=True)
class AbsorptionDiagnostic:
    window_id: str
    state: str
    centers_um: np.ndarray
    continuum_removed: np.ndarray
    apparent_depth: float | None
    sampled_minimum_um: float | None
    minimum_at_search_edge: bool | None

    def summary(self) -> dict:
        return {
            "window_id": self.window_id, "state": self.state,
            "usable_search_bins": len(self.centers_um),
            "apparent_depth": self.apparent_depth,
            "sampled_minimum_um": self.sampled_minimum_um,
            "minimum_at_search_edge": self.minimum_at_search_edge,
            "claim": "Broad continuum-relative diagnostic; no mineral identity or abundance",
        }


def absorption_diagnostic(source: Spectrum, window: AbsorptionWindow) -> AbsorptionDiagnostic:
    selections = [(source.wavelength_um >= lo - 1e-12) &
                  (source.wavelength_um <= hi + 1e-12)
                  for lo, hi in (window.left_shoulder_um, window.search_um,
                                 window.right_shoulder_um)]
    if any(not selection.any() or not source.valid[selection].all()
           for selection in selections):
        return AbsorptionDiagnostic(window.id, "insufficient_overlap", np.array([]),
                                     np.array([]), None, None, None)
    left, search, right = selections
    shoulder_x = [source.wavelength_um[s].mean() for s in (left, right)]
    shoulder_y = [source.reflectance[s].mean() for s in (left, right)]
    coordinates = source.wavelength_um[search]
    continuum = np.interp(coordinates, shoulder_x, shoulder_y)
    if np.any(continuum <= 0):
        return AbsorptionDiagnostic(window.id, "insufficient_overlap", np.array([]),
                                     np.array([]), None, None, None)
    ratios = source.reflectance[search] / continuum
    index = int(np.argmin(ratios))
    return AbsorptionDiagnostic(
        window.id, "candidate_absorption_only", coordinates, ratios,
        float(1 - ratios[index]), float(coordinates[index]),
        index in {0, len(ratios) - 1},
    )


def compare_reflectance(field: Spectrum, lab: Spectrum,
                        windows: tuple[AbsorptionWindow, ...], minimum_bins: int) -> dict:
    if not np.array_equal(field.wavelength_um, lab.wavelength_um):
        raise ValueError("Compare spectra only on the same declared common grid")
    valid = field.valid & lab.valid
    if int(valid.sum()) < minimum_bins:
        return {"state": "insufficient_overlap", "common_bins": int(valid.sum()),
                "spectral_angle_radians": None, "reflectance_rmse": None,
                "continuum_removed_rmse": None, "absorption_diagnostics": []}
    diagnostics, residuals = [], []
    all_windows_usable = True
    for window in windows:
        a, b = absorption_diagnostic(field, window), absorption_diagnostic(lab, window)
        usable = a.apparent_depth is not None and b.apparent_depth is not None
        all_windows_usable &= usable
        if usable:
            residuals.extend((a.continuum_removed - b.continuum_removed).tolist())
        diagnostics.append({
            "window_id": window.id, "field": a.summary(), "lab": b.summary(),
            "lab_minus_field_apparent_depth": b.apparent_depth - a.apparent_depth
            if usable else None,
            "lab_minus_field_sampled_minimum_um": b.sampled_minimum_um -
            a.sampled_minimum_um if usable else None,
        })
    return {
        "state": "known_control_characterization", "common_bins": int(valid.sum()),
        "spectral_angle_radians": spectral_angle(field, lab)["angle_radians"],
        "reflectance_rmse": float(np.sqrt(np.mean(
            (field.reflectance[valid] - lab.reflectance[valid]) ** 2))),
        "continuum_removed_rmse": float(np.sqrt(np.mean(np.square(residuals))))
        if all_windows_usable and residuals else None,
        "continuum_search_bin_count": len(residuals) if all_windows_usable else 0,
        "absorption_diagnostics": diagnostics,
    }


def characterize_archive(root: Path, protocol_path: Path) -> dict:
    """Describe same-ID agreement against all paired-set different-ID controls."""
    protocol = ControlProtocol.read(protocol_path)
    measurements, records = read_archive(root, protocol)
    spectra = {kind: {} for kind in ("field_vnir", "lab_vnir")}
    for measurement in measurements:
        native = measurement.reflectance_spectrum()
        if native is not None:
            spectra[measurement.spec.kind][measurement.spec.sample_id] = box_average(
                native, protocol.edges_um, protocol.max_native_gap_um)
    paired_ids = sorted(set(spectra["field_vnir"]) & set(spectra["lab_vnir"]))
    comparisons = []
    for field_id in paired_ids:
        for lab_id in paired_ids:
            comparisons.append({
                "field_sample_id": field_id, "lab_sample_id": lab_id,
                "same_sample": field_id == lab_id,
                **compare_reflectance(spectra["field_vnir"][field_id],
                    spectra["lab_vnir"][lab_id], protocol.windows,
                    protocol.minimum_common_bins),
            })
    metrics = ("spectral_angle_radians", "reflectance_rmse", "continuum_removed_rmse")
    matched, mismatched = [], []
    for comparison in comparisons:
        if not comparison["same_sample"]:
            mismatched.append(comparison)
            continue
        row = {"sample_id": comparison["field_sample_id"], **comparison, "ranks": {}}
        for metric in metrics:
            value = comparison[metric]
            candidates = [c[metric] for c in comparisons
                          if c["field_sample_id"] == row["sample_id"]
                          and c[metric] is not None]
            row["ranks"][metric] = None if value is None else {
                "best_rank": 1 + int(sum(v < value and not np.isclose(v, value,
                    rtol=1e-10, atol=1e-12) for v in candidates)),
                "worst_rank": int(sum(v < value or np.isclose(v, value,
                    rtol=1e-10, atol=1e-12) for v in candidates)),
                "candidate_count": len(candidates),
            }
        matched.append(row)
    summary = {
        "native_file_count": len(measurements),
        "measurement_counts": {kind: sum(m.spec.kind == kind for m in measurements)
                               for kind in ("field_vnir", "lab_vnir", "ftir", "xrd")},
        "paired_sample_count": len(paired_ids), "matched_pair_count": len(matched),
        "mismatch_pair_count": len(mismatched),
        "common_bin_count": len(protocol.edges_um) - 1,
        "unpaired_field_sample_ids": sorted(set(spectra["field_vnir"]) - set(paired_ids)),
        "unpaired_lab_sample_ids": sorted(set(spectra["lab_vnir"]) - set(paired_ids)),
    }
    for label, rows in (("matched", matched), ("mismatch", mismatched)):
        summary[label] = {}
        for metric in metrics:
            values = [row[metric] for row in rows if row[metric] is not None]
            summary[label][metric] = {
                "count": len(values),
                "median": float(np.median(values)) if values else None,
                "min": min(values) if values else None,
                "max": max(values) if values else None,
            }
    for label, metric in (("sam", "spectral_angle_radians"),
                          ("continuum_rmse", "continuum_removed_rmse")):
        summary[f"same_sample_nearest_by_{label}_count"] = sum(
            row["ranks"][metric] is not None and row["ranks"][metric]["best_rank"] == 1
            for row in matched)
        summary[f"same_sample_unique_nearest_by_{label}_count"] = sum(
            row["ranks"][metric] is not None and row["ranks"][metric]["worst_rank"] == 1
            for row in matched)
    return {
        "schema_version": 1, "experiment_id": protocol.payload["experiment_id"],
        "state": "known_control_characterization", "mineral_assignment": None,
        "summary": summary, "matched_pairs": matched,
        "mismatch_pairs": mismatched, "measurements": [m.summary() for m in measurements],
        "sources": records,
        "lineage": {"protocol": file_lineage(protocol_path, root),
                    "implementation": file_lineage(Path(__file__).resolve(), root),
                    "numpy_version": np.__version__},
        "protocol": protocol.payload,
        "uncertainty": {
            "measurement_uncertainty": None, "confidence_intervals": None,
            "reason": "Archived means have no replicates or calibrated noise model; wavelength bins and the 90 dependent mismatch pairs are not independent replicates.",
            "sampled_minimum_grid_spacing_um": protocol.box_width_um,
            "grid_spacing_is_measurement_uncertainty": False,
        },
        "limitations": protocol.payload["limitations"],
    }
