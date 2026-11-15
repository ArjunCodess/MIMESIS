"""Source-backed orbital spectroscopy intake and explicit evidence abstention.

EMIT stays in instrument space for spectral statistics. GLT output is useful
for display and coverage, never a source of independent geological replicates.
"""

from dataclasses import dataclass
from collections import OrderedDict
import hashlib
import io
import json
import math
from pathlib import Path
import re
import time
import xml.etree.ElementTree as ET

import numpy as np
from netCDF4 import Dataset

from src.spectra import Spectrum, response_match


def reference_emit_approximation(source, centers_um, fwhm_um, masked_intervals_um,
                                 minimum_axis_mass=0.99):
    """Gaussian approximation with explicit unobserved response-tail abstention."""
    matched = response_match(source, centers_um, fwhm_um)
    sigma = fwhm_um / 2.355
    axis_mass = np.array([
        .5 * (math.erf((source.wavelength_um[-1] - center) / (width * math.sqrt(2)))
              - math.erf((source.wavelength_um[0] - center) / (width * math.sqrt(2))))
        for center, width in zip(centers_um, sigma)
    ])
    valid = matched.valid & (axis_mass >= minimum_axis_mass)
    for lo, hi in masked_intervals_um:
        valid[(centers_um >= lo) & (centers_um <= hi)] = False
    return Spectrum(centers_um, matched.reflectance, valid, matched.source_id)


def fixed_continuum_feature(spectrum, feature):
    """Require the entire fixed support; never replace missing channels per pair."""
    regions = [(spectrum.wavelength_um >= lo) & (spectrum.wavelength_um <= hi)
               for lo, hi in (feature["left_shoulder_um"], feature["search_um"],
                              feature["right_shoulder_um"])]
    required = np.logical_or.reduce(regions)
    unavailable = required & ~spectrum.valid
    base = {"id": feature["id"], "required_channels": int(required.sum()),
            "unavailable_required_channel_centers_um": spectrum.wavelength_um[unavailable].tolist(),
            "depth": None, "sampled_minimum_um": None,
            "uncertainty_state": "depth_confidence_not_estimated_pixel_SD_is_not_depth_covariance"}
    if any(s.sum() < feature["minimum_channels_per_region"] for s in regions) or unavailable.any():
        return {**base, "state": "abstain_incomplete_fixed_support"}
    left, search, right = regions
    shoulder_x = [spectrum.wavelength_um[s].mean() for s in (left, right)]
    shoulder_y = [spectrum.reflectance[s].mean() for s in (left, right)]
    continuum = np.interp(spectrum.wavelength_um[search], shoulder_x, shoulder_y)
    if np.any(continuum <= 0):
        return {**base, "state": "abstain_nonpositive_continuum"}
    ratios = spectrum.reflectance[search] / continuum
    minimum = int(np.argmin(ratios))
    return {**base, "state": "descriptive_apparent_absorption_only",
            "depth": float(1 - ratios[minimum]),
            "sampled_minimum_um": float(spectrum.wavelength_um[search][minimum]),
            "minimum_at_search_edge": minimum in {0, len(ratios)-1},
            "search_centers_um": spectrum.wavelength_um[search].tolist(),
            "continuum_removed_search": ratios.tolist(),
            "shoulder_mean_wavelengths_um": [float(x) for x in shoulder_x],
            "shoulder_mean_reflectance": [float(x) for x in shoulder_y]}


def compare_fixed_features(left, right):
    """A descriptive difference only when both fixed observables are available."""
    if left["depth"] is None or right["depth"] is None:
        return {"state": "abstain_incomplete_fixed_support", "depth_difference": None,
                "continuum_relative_rmse": None}
    if left["search_centers_um"] != right["search_centers_um"]:
        raise ValueError("Feature comparisons require identical fixed search channels")
    difference = np.asarray(left["continuum_removed_search"]) - right["continuum_removed_search"]
    return {"state": "descriptive_cross_observable_difference_only",
            "depth_difference": left["depth"] - right["depth"],
            "continuum_relative_rmse": float(np.sqrt(np.mean(difference ** 2)))}


class HttpRangeReader(io.RawIOBase):
    """Seekable, bounded HTTPS reader; every response must confirm its byte range."""

    def __init__(self, url, session, byte_budget=512 * 1024 * 1024, *,
                 block_size=1024 * 1024, cache_blocks=64, request_cap=128,
                 time_cap_seconds=300, progress=None):
        self.url, self.session, self.budget = url, session, byte_budget
        if block_size < 8 or cache_blocks < 1 or request_cap < 2 or time_cap_seconds <= 0:
            raise ValueError("Positive cache blocks, request/time caps and at least eight-byte blocks required")
        self.position, self.transferred, self.ranges = 0, 0, []
        self.block_size, self.cache_blocks = block_size, cache_blocks
        self.cache = OrderedDict()
        self.request_cap, self.time_cap_seconds = request_cap, time_cap_seconds
        self.started, self.request_count, self.progress = time.monotonic(), 1, progress
        with session.get(url, headers={"Range": "bytes=0-7", "Accept-Encoding": "identity"}, timeout=(10, 15), stream=True) as response:
            response.raise_for_status()
            content_range = response.headers.get("Content-Range", "")
            if response.status_code != 206 or not content_range.startswith("bytes 0-7/"):
                raise ValueError("Source does not provide verified HDF5 HTTP byte ranges")
            if response.raw.read(9) != b"\x89HDF\r\n\x1a\n":
                raise ValueError("Source byte signature is not HDF5")
        self.size = int(content_range.split("/")[-1])
        self.transferred = 8
        if self.progress:
            self.progress(f"Verified HDF5 ranges; source {self.size:,} bytes; cap {self.budget:,} bytes, {request_cap} requests, {time_cap_seconds}s")

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        position = offset if whence == 0 else self.position + offset if whence == 1 else self.size + offset
        if position < 0:
            raise ValueError("Negative source offset")
        self.position = position
        return position

    def read(self, size=-1):
        end = self.size if size < 0 else min(self.size, self.position + size)
        if end <= self.position:
            return b""
        pieces = []
        while self.position < end:
            index = self.position // self.block_size
            if index not in self.cache:
                # Metadata reads fetch one aligned block. Large HDF5 chunk reads
                # coalesce up to eight needed blocks into one HTTP request.
                last = min((end - 1) // self.block_size, index + 7, index + self.cache_blocks - 1)
                for candidate in range(index + 1, last + 1):
                    if candidate in self.cache:
                        last = candidate - 1
                        break
                start = index * self.block_size
                stop = min(self.size, (last + 1) * self.block_size)
                content = self._fetch(start, stop)
                for block_index in range(index, last + 1):
                    offset = (block_index - index) * self.block_size
                    self.cache[block_index] = content[offset:offset + self.block_size]
                    self.cache.move_to_end(block_index)
                    while len(self.cache) > self.cache_blocks:
                        self.cache.popitem(last=False)
            block = self.cache[index]
            self.cache.move_to_end(index)
            offset = self.position % self.block_size
            length = min(len(block) - offset, end - self.position)
            pieces.append(block[offset:offset + length])
            self.position += length
        return b"".join(pieces)

    def _fetch(self, start, end):
        elapsed = time.monotonic() - self.started
        if self.request_count >= self.request_cap or elapsed >= self.time_cap_seconds:
            raise ValueError("Range acquisition exceeds per-source request/time cap")
        if self.transferred + end - start > self.budget:
            raise ValueError("Range acquisition exceeds declared per-asset byte budget")
        self.request_count += 1
        if self.progress:
            self.progress(f"Range request {self.request_count}/{self.request_cap}; fetched {self.transferred / 1048576:.1f} MiB; next {(end-start)/1048576:.1f} MiB; elapsed {elapsed:.0f}s")
        remaining = self.time_cap_seconds - elapsed
        with self.session.get(self.url, headers={"Range": f"bytes={start}-{end-1}", "Accept-Encoding": "identity"}, timeout=(min(10, remaining), min(15, remaining)), stream=True) as response:
            response.raise_for_status()
            expected = f"bytes {start}-{end-1}/{self.size}"
            if response.status_code != 206 or response.headers.get("Content-Range") != expected:
                raise ValueError("Source returned an unverified byte range")
            content = response.raw.read(end-start+1)
            if len(content) != end-start:
                raise ValueError("Source returned an incomplete byte range")
        self.transferred += end-start
        self.ranges.append([start, end-1])
        return content

    def readinto(self, buffer):
        data = self.read(len(buffer))
        buffer[:len(data)] = data
        return len(data)


def acquire_emit_rectangle(reflectance_url, uncertainty_url, rectangle, session, output_path,
                           byte_budget=512 * 1024 * 1024):
    """Materialize a named derived ROI from validated source ranges, never a full cube."""
    import h5py

    r0, r1, c0, c1 = rectangle
    key = (slice(r0, r1+1), slice(c0, c1+1), slice(None))
    arrays, metadata = {}, []
    for kind, url, variable in (("reflectance", reflectance_url, "reflectance"),
                               ("uncertainty", uncertainty_url, "reflectance_uncertainty")):
        print(f"Acquiring {kind} native rectangle {rectangle}", flush=True)
        reader = HttpRangeReader(url, session, byte_budget,
                                 progress=lambda message: print(f"{kind}: {message}", flush=True))
        with h5py.File(reader, "r") as source:
            native = source[variable]
            values = np.asarray(native[key], dtype=float)
            fill = native.attrs.get("_FillValue", -9999)
            values[values == fill] = np.nan
            params = source["sensor_band_parameters"]
            wave = np.asarray(params["wavelengths"][:])
            widths = np.asarray(params["fwhm"][:])
            location = {name: np.asarray(source["location"][name][key[:2]]) for name in ("lon", "lat")}
            transform = np.asarray(source.attrs["geotransform"])
            wave_units = params["wavelengths"].attrs.get("units", "nm")
            width_units = params["fwhm"].attrs.get("units", "nm")
            wave_units = wave_units.decode() if isinstance(wave_units, bytes) else str(wave_units)
            width_units = width_units.decode() if isinstance(width_units, bytes) else str(width_units)
            if arrays and not (np.array_equal(wave, arrays["wavelengths"]) and np.array_equal(location["lon"], arrays["lon"]) and np.array_equal(location["lat"], arrays["lat"])):
                raise ValueError("Source reflectance and uncertainty ROI metadata differ")
            arrays.update({variable: values, "wavelengths": wave, "fwhm": widths, **location})
            metadata.append({"kind": kind, "source_url": url, "full_native_shape": list(native.shape),
                             "source_bytes": reader.size, "transferred_bytes": reader.transferred,
                             "http_logical_requests": reader.request_count,
                             "range_policy": {"aligned_block_bytes": reader.block_size, "cache_blocks": reader.cache_blocks, "coalesced_blocks_per_request": 8, "logical_request_cap": reader.request_cap, "time_cap_seconds": reader.time_cap_seconds, "cap_interpretation": "Checked before each request; active request has bounded connect/read timeouts"},
                             "verified_byte_ranges_inclusive": reader.ranges,
                             "source_hash_state": "full_source_sha256_not_computed_for_range_subset"})
    output_path.parent.mkdir(parents=True, exist_ok=True)
    partial = output_path.with_suffix(".nc.part")
    with Dataset(partial, "w") as out:
        for name, size in zip(("roi_y", "roi_x", "bands"), arrays["reflectance"].shape):
            out.createDimension(name, size)
        out.product_role = "derived_native_rectangle_not_full_source_granule"
        out.source_native_rectangle_inclusive = rectangle
        out.source_metadata_json = json.dumps(metadata)
        out.geotransform = transform
        out.wavelength_unit_evidence = "Source attributes; absent attributes use documented EMIT L2A user-guide nm contract"
        for name in ("reflectance", "reflectance_uncertainty"):
            out.createVariable(name, "f4", ("roi_y", "roi_x", "bands"), zlib=True, fill_value=np.nan)[:] = arrays[name]
        for name in ("lon", "lat"):
            out.createVariable(name, "f8", ("roi_y", "roi_x"))[:] = arrays[name]
        for name, units in (("wavelengths", wave_units), ("fwhm", width_units)):
            variable = out.createVariable(name, "f8", ("bands",))
            variable.units = units
            variable[:] = arrays[name]
    partial.replace(output_path)
    return metadata


def read_derived_emit_roi(path, mask, bbox, required_flags, masked_intervals_um):
    with Dataset(path) as ds:
        if ds.product_role != "derived_native_rectangle_not_full_source_granule":
            raise ValueError("Expected explicitly derived ROI product")
        r0, r1, c0, c1 = map(int, ds.source_native_rectangle_inclusive)
        crop = (slice(r0, r1+1), slice(c0, c1+1))
        lon, lat = read_variable(ds["lon"]), read_variable(ds["lat"])
        if not (np.array_equal(lon, mask.lon[crop]) and np.array_equal(lat, mask.lat[crop])
                and np.array_equal(ds.geotransform, mask.geotransform)):
            raise ValueError("Derived ROI original native offsets or geolocation do not match mask")
        roi = roi_centers(lon, lat, bbox) & mask.clear(required_flags)[crop]
        wave = wavelength_um(ds["wavelengths"][:], ds["wavelengths"].units)
        widths = np.asarray(ds["fwhm"][:])
        units = ds["fwhm"].units
        if units not in {"nm", "um"} or np.any(widths <= 0) or not np.isfinite(widths).all():
            raise ValueError("Derived response widths require finite positive nm/um values")
        widths = widths * (0.001 if units == "nm" else 1)
        values = read_variable(ds["reflectance"])[roi]
        errors = read_variable(ds["reflectance_uncertainty"])[roi]
        bad = unpack_band_mask(mask.packed[crop][roi], len(wave))
        valid = ~bad & np.isfinite(values) & (values > 0) & np.isfinite(errors) & (errors >= 0)
        for lo, hi in masked_intervals_um:
            valid[:, (wave >= lo) & (wave <= hi)] = False
        return EmitRoiSpectra(wave, widths, values, errors, valid, path.name)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def wavelength_um(values, units: str) -> np.ndarray:
    """Convert a declared wavelength axis; guessing from magnitudes is forbidden."""
    scales = {"nm": 0.001, "nanometers": 0.001, "nanometres": 0.001,
              "um": 1.0, "micrometers": 1.0, "micrometres": 1.0}
    if units.lower() not in scales:
        raise ValueError(f"Unsupported or missing wavelength units: {units!r}")
    result = np.asarray(values, dtype=float) * scales[units.lower()]
    if result.ndim != 1 or not np.isfinite(result).all() or np.any(np.diff(result) <= 0):
        raise ValueError("Wavelength centers must be finite and strictly increasing")
    return result


def unpack_band_mask(packed: np.ndarray, bands: int = 285) -> np.ndarray:
    """NASA emit_tools packs the first channel in the most significant bit."""
    if packed.dtype != np.uint8 or packed.ndim < 1 or not 0 < bands <= packed.shape[-1] * 8:
        raise ValueError("Band mask requires uint8 packed bytes covering every channel")
    return np.unpackbits(packed, axis=-1, bitorder="big")[..., :bands].astype(bool)


def project_glt(native: np.ndarray, glt_x: np.ndarray, glt_y: np.ndarray) -> np.ndarray:
    """Apply one-based EMIT GLT, preserving zero/invalid cells as NaN."""
    if glt_x.shape != glt_y.shape or glt_x.ndim != 2 or native.ndim < 2:
        raise ValueError("GLT x/y must share a 2D grid and reference a native image")
    valid = ((glt_x > 0) & (glt_y > 0) & (glt_x <= native.shape[1])
             & (glt_y <= native.shape[0]))
    result = np.full((*glt_x.shape, *native.shape[2:]), np.nan)
    result[valid] = native[glt_y[valid].astype(int) - 1, glt_x[valid].astype(int) - 1]
    return result


def roi_centers(lon: np.ndarray, lat: np.ndarray, bbox) -> np.ndarray:
    west, south, east, north = bbox
    if lon.shape != lat.shape or lon.ndim != 2 or not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("ROI requires matching 2D locations and ordered WGS84 bounds")
    return np.isfinite(lon) & np.isfinite(lat) & (lon >= west) & (lon <= east) & (lat >= south) & (lat <= north)


def read_variable(variable, key=Ellipsis):
    """netCDF owns fill-value/scale decoding; convert masked data once."""
    return np.asarray(np.ma.filled(variable[key], np.nan), dtype=float)


@dataclass(frozen=True)
class EmitMask:
    lon: np.ndarray
    lat: np.ndarray
    flags: np.ndarray
    names: tuple[str, ...]
    packed: np.ndarray
    glt_x: np.ndarray
    glt_y: np.ndarray
    geotransform: np.ndarray
    source_id: str

    @classmethod
    def read(cls, path: Path):
        with Dataset(path) as ds:
            loc = ds.groups["location"]
            names = tuple(str(x) for x in ds.groups["sensor_band_parameters"]["mask_bands"][:])
            lon, lat = read_variable(loc["lon"]), read_variable(loc["lat"])
            flags = read_variable(ds["mask"])
            packed = np.asarray(ds["band_mask"][:])
            if (flags.shape != (*lon.shape, len(names)) or lat.shape != lon.shape
                    or packed.shape[:2] != lon.shape or packed.dtype != np.uint8):
                raise ValueError("EMIT mask, packed bands and native locations do not align")
            return cls(lon, lat, flags, names, packed,
                       np.asarray(loc["glt_x"][:]), np.asarray(loc["glt_y"][:]),
                       np.asarray(ds.geotransform, dtype=float), path.name)

    def clear(self, required_flags) -> np.ndarray:
        missing = set(required_flags) - set(self.names)
        if missing:
            raise ValueError(f"Missing required quality flags: {sorted(missing)}")
        flags = self.flags[..., [self.names.index(name) for name in required_flags]]
        return np.isfinite(flags).all(axis=-1) & (flags == 0).all(axis=-1)

    def inventory(self, bbox, required_flags):
        roi = roi_centers(self.lon, self.lat, bbox)
        clear = self.clear(required_flags)
        rows, cols = np.nonzero(roi)
        slices = None if not len(rows) else [int(rows.min()), int(rows.max()), int(cols.min()), int(cols.max())]
        projected = project_glt((roi & clear).astype(float), self.glt_x, self.glt_y)
        return {
            "native_roi_centers": int(roi.sum()),
            "native_clear_centers": int((roi & clear).sum()),
            "clear_fraction_of_native_centers": float(clear[roi].mean()) if roi.any() else None,
            "native_rectangle_inclusive": slices,
            "flagged_native_centers": {name: int((roi & (self.flags[..., i] != 0)).sum()) for i, name in enumerate(self.names) if "flag" in name.lower()},
            "glt_cells_mapping_to_clear_native_roi": int(np.nansum(projected)),
            "count_interpretation": "Native centers and repeated GLT cells are neither area estimates nor independent geological replicates",
        }


@dataclass(frozen=True)
class EmitRoiSpectra:
    wavelength_um: np.ndarray
    fwhm_um: np.ndarray
    reflectance: np.ndarray
    uncertainty: np.ndarray
    valid: np.ndarray
    source_id: str

    def descriptive_summary(self):
        counts = self.valid.sum(axis=0)
        mean = np.divide(np.where(self.valid, self.reflectance, 0).sum(axis=0), counts,
                         out=np.full(len(counts), np.nan), where=counts > 0)
        # Mean supplied pixel SD is descriptive. It is not SE of a unit mean.
        sd = np.divide(np.where(self.valid, self.uncertainty, 0).sum(axis=0), counts,
                       out=np.full(len(counts), np.nan), where=counts > 0)
        return {"wavelength_um": self.wavelength_um.tolist(), "fwhm_um": self.fwhm_um.tolist(),
                "valid_native_centers_per_channel": counts.tolist(),
                "mean_reflectance": [float(x) if np.isfinite(x) else None for x in mean],
                "mean_supplied_pixel_posterior_sd": [float(x) if np.isfinite(x) else None for x in sd],
                "uncertainty_interpretation": "Supplied posterior per-pixel channel SD; spatial covariance, continuum-error covariance and geological heterogeneity are not estimated"}


def read_emit_roi(reflectance_path: Path, uncertainty_path: Path, mask: EmitMask, bbox,
                  required_flags, masked_intervals_um) -> EmitRoiSpectra:
    roi = roi_centers(mask.lon, mask.lat, bbox) & mask.clear(required_flags)
    rows, cols = np.nonzero(roi)
    if not len(rows):
        raise ValueError("No quality-eligible native ROI centers")
    # Read a small bounding rectangle, then pair rows and columns locally.
    r0, r1, c0, c1 = rows.min(), rows.max() + 1, cols.min(), cols.max() + 1
    key = (slice(r0, r1), slice(c0, c1), slice(None))
    with Dataset(reflectance_path) as rfl, Dataset(uncertainty_path) as unc:
        rv, uv = rfl["reflectance"], unc["reflectance_uncertainty"]
        if rv.shape != uv.shape or rv.shape[:2] != mask.lon.shape:
            raise ValueError("Reflectance, uncertainty and mask native grids do not align")
        for ds in (rfl, unc):
            if not np.array_equal(np.asarray(ds.geotransform), mask.geotransform):
                raise ValueError("Product geotransforms do not align")
            loc = ds.groups["location"]
            k2 = key[:2]
            if not (np.array_equal(read_variable(loc["lon"], k2), mask.lon[k2], equal_nan=True)
                    and np.array_equal(read_variable(loc["lat"], k2), mask.lat[k2], equal_nan=True)):
                raise ValueError("Product geolocation differs within requested rectangle")
        params = rfl.groups["sensor_band_parameters"]
        wave = wavelength_um(params["wavelengths"][:], params["wavelengths"].units)
        fwhm = np.asarray(params["fwhm"][:], dtype=float)
        fwhm_units = params["fwhm"].units.lower()
        if fwhm_units not in {"nm", "um"}:
            raise ValueError("Explicit nm/um response width units required")
        fwhm *= 0.001 if fwhm_units == "nm" else 1
        up = unc.groups["sensor_band_parameters"]
        uw = wavelength_um(up["wavelengths"][:], up["wavelengths"].units)
        if not np.array_equal(wave, uw) or len(wave) != rv.shape[-1] or not np.isfinite(fwhm).all() or np.any(fwhm <= 0):
            raise ValueError("Uncertainty wavelengths and positive response widths must align")
        values = read_variable(rv, key)[rows - r0, cols - c0]
        errors = read_variable(uv, key)[rows - r0, cols - c0]
    bad = unpack_band_mask(mask.packed[rows, cols], len(wave))
    valid = ~bad & np.isfinite(values) & (values > 0) & np.isfinite(errors) & (errors >= 0)
    for lo, hi in masked_intervals_um:
        valid[:, (wave >= lo) & (wave <= hi)] = False
    return EmitRoiSpectra(wave, fwhm, values, errors, valid, reflectance_path.name)


def diagnostic_availability(wavelengths, valid, interval_um, masked_intervals_um):
    lo, hi = interval_um
    if any(a <= hi and b >= lo for a, b in masked_intervals_um):
        return {"state": "abstain", "reason": "diagnostic_overlaps_prespecified_atmospheric_mask"}
    selected = (wavelengths >= lo) & (wavelengths <= hi)
    if not selected.any() or not valid[..., selected].any():
        return {"state": "abstain", "reason": "no_valid_diagnostic_channels"}
    return {"state": "candidate_absorption_support_only", "reason": "mineral_identity_requires_independent_geological_controls"}


def read_crism_wavelength_table(table_path: Path, label_path: Path):
    """Read the actual five-column MTRDR WV contract from its PDS4 label."""
    ns = {"p": "http://pds.nasa.gov/pds4/pds/v1"}
    label = ET.parse(label_path)
    fields = label.findall(".//p:Field_Character", ns)
    names = [field.findtext("p:name", namespaces=ns) for field in fields]
    if names != ["spect_id", "rownum", "sampl_wav", "fwhm", "bad_band_id"]:
        raise ValueError("Unsupported CRISM WV PDS4 field contract")
    if any(fields[i].findtext("p:unit", namespaces=ns) != "nm" for i in (2, 3)):
        raise ValueError("CRISM WV requires declared nm center and FWHM units")
    files = [n.text for n in label.findall(".//p:File/p:file_name", ns)]
    if table_path.name not in files:
        raise ValueError("WV table is not referenced by its source label")
    rows = np.loadtxt(table_path, delimiter=",")
    if rows.ndim != 2 or rows.shape[1] != 5 or not np.isfinite(rows).all():
        raise ValueError("CRISM WV table requires five finite columns")
    if np.any(rows[:, 3] <= 0) or not np.isin(rows[:, 4], [0, 1]).all():
        raise ValueError("CRISM WV widths and bad-band flags are invalid")
    return wavelength_um(rows[:, 2], "nm"), rows[:, 3] / 1000, rows[:, 4].astype(bool)


def read_envi_cube(header_path: Path, data_path: Path, *, wv_table: Path | None = None,
                   wv_label: Path | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Strict ENVI boundary for independently verified CRISM exports, not PDS parsing.

    No mineral labels or wavelengths are inferred from filenames. PDS IF, WV,
    IN and DE labels/geometry still need independent product registration.
    """
    text = header_path.read_text(encoding="utf-8")
    fields = {k.strip().lower(): v.strip() for k, v in re.findall(r"([^\n=]+)=\s*(\{[^}]*\}|[^\n]+)", text)}
    if fields.get("wavelength units", "").lower() not in {"nanometers", "micrometers", "nm", "um"}:
        raise ValueError("ENVI wavelength units must be explicit")
    wave = wavelength_um(np.fromstring(fields["wavelength"].strip("{}"), sep=","), fields["wavelength units"])
    lines, samples, bands = (int(fields[k]) for k in ("lines", "samples", "bands"))
    if min(lines, samples, bands) <= 0 or len(wave) != bands:
        raise ValueError("ENVI dimensions and wavelength count must agree")
    types = {4: "f4", 5: "f8"}
    dtype_code = int(fields["data type"])
    byte_order = int(fields["byte order"])
    if dtype_code not in types or byte_order not in {0, 1}:
        raise ValueError("Only explicit-endian floating reflectance exports are supported")
    offset = int(fields.get("header offset", "0"))
    dtype = np.dtype(("<" if byte_order == 0 else ">") + types[dtype_code])
    if offset < 0 or data_path.stat().st_size != offset + lines * samples * bands * dtype.itemsize:
        raise ValueError("ENVI binary size does not match declared dimensions")
    raw = np.memmap(data_path, dtype=dtype, mode="r", offset=offset)
    interleave = fields["interleave"].lower()
    if interleave == "bsq":
        cube = raw.reshape(bands, lines, samples).transpose(1, 2, 0)
    elif interleave == "bil":
        cube = raw.reshape(lines, bands, samples).transpose(0, 2, 1)
    elif interleave == "bip":
        cube = raw.reshape(lines, samples, bands)
    else:
        raise ValueError("Unsupported ENVI interleave")
    valid = np.isfinite(cube) & (cube > 0)
    if "data ignore value" in fields:
        valid &= cube != float(fields["data ignore value"])
    if wv_table is not None and wv_label is not None:
        wv_wave, _, bbl = read_crism_wavelength_table(wv_table, wv_label)
        if not np.allclose(wave, wv_wave, rtol=0, atol=1e-8):
            raise ValueError("ENVI wavelengths differ from registered PDS4 WV table")
    elif "bbl" in fields:
        bbl = np.fromstring(fields["bbl"].strip("{}"), sep=",")
    else:
        raise ValueError("Explicit ENVI bad-band list or registered WV table required")
    if len(bbl) != bands or not np.isin(bbl, [0, 1]).all():
        raise ValueError("ENVI bad-band list must contain one binary value per band")
    return cube, wave, valid & bbl.astype(bool)
