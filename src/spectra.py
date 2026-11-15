"""Explicit optional cross-sensor spectral experiment, excluded from terrain loss."""

from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class Spectrum:
    wavelength_um: np.ndarray
    reflectance: np.ndarray
    valid: np.ndarray
    source_id: str

    def __post_init__(self):
        wave = self.wavelength_um
        if (
            wave.ndim != 1
            or len(wave) < 3
            or not np.isfinite(wave).all()
            or np.any(np.diff(wave) <= 0)
        ):
            raise ValueError(
                "Wavelengths must be finite, strictly increasing micrometres"
            )
        if (
            self.reflectance.shape != wave.shape
            or self.valid.shape != wave.shape
            or self.valid.dtype != bool
        ):
            raise ValueError("Reflectance and boolean validity must match wavelengths")
        if not np.isfinite(self.reflectance[self.valid]).all():
            raise ValueError("Valid spectral samples must be finite")


def response_match(source: Spectrum, centers_um: np.ndarray, fwhm_um: np.ndarray):
    if (
        centers_um.ndim != 1
        or fwhm_um.shape != centers_um.shape
        or np.any(fwhm_um <= 0)
        or not np.isfinite(fwhm_um).all()
        or not np.isfinite(centers_um).all()
    ):
        raise ValueError(
            "Band centers and positive finite FWHM must have matching shapes"
        )
    result, valid = [], []
    for center, width in zip(centers_um, fwhm_um):
        sigma = width / 2.355
        response = np.exp(-0.5 * ((source.wavelength_um - center) / sigma) ** 2)
        # Integrate over wavelength; irregular wavelength sampling is not equal-area.
        response *= np.gradient(source.wavelength_um)
        in_range = (
            source.wavelength_um[0] <= center - width
            and source.wavelength_um[-1] >= center + width
        )
        support = (
            response[source.valid].sum() / response.sum() if response.sum() > 0 else 0
        )
        usable = bool(in_range and support >= 0.99)
        valid.append(usable)
        result.append(
            float(
                np.dot(response[source.valid], source.reflectance[source.valid])
                / response[source.valid].sum()
            )
            if usable
            else np.nan
        )
    return Spectrum(
        centers_um,
        np.asarray(result),
        np.asarray(valid),
        source.source_id + ":gaussian-response-approximation",
    )


def continuum_removed(spectrum: Spectrum, anchors_um: tuple[float, float]):
    lo, hi = anchors_um
    anchors = [
        int(np.argmin(abs(spectrum.wavelength_um - wavelength)))
        for wavelength in (lo, hi)
    ]
    if lo >= hi or anchors[0] == anchors[1] or not spectrum.valid[anchors].all():
        raise ValueError("Distinct valid continuum anchors are required")
    continuum = np.interp(
        spectrum.wavelength_um,
        spectrum.wavelength_um[anchors],
        spectrum.reflectance[anchors],
    )
    valid = (
        spectrum.valid
        & (spectrum.wavelength_um >= lo)
        & (spectrum.wavelength_um <= hi)
        & (continuum > 0)
    )
    values = np.full_like(spectrum.reflectance, np.nan, dtype=float)
    values[valid] = spectrum.reflectance[valid] / continuum[valid]
    return Spectrum(
        spectrum.wavelength_um, values, valid, spectrum.source_id + ":continuum-removed"
    )


def spectral_angle(a: Spectrum, b: Spectrum):
    if not np.array_equal(a.wavelength_um, b.wavelength_um):
        raise ValueError("Response-match both spectra before computing SAM")
    valid = a.valid & b.valid
    if valid.sum() < 3:
        return {
            "state": "insufficient_evidence",
            "valid_bands": int(valid.sum()),
            "angle_radians": None,
        }
    left, right = a.reflectance[valid], b.reflectance[valid]
    norm = float(np.linalg.norm(left) * np.linalg.norm(right))
    if norm == 0:
        return {
            "state": "insufficient_evidence",
            "valid_bands": int(valid.sum()),
            "angle_radians": None,
        }
    return {
        "state": "spectral_similarity_only",
        "angle_radians": float(np.arccos(np.clip(np.dot(left, right) / norm, -1, 1))),
        "valid_bands": int(valid.sum()),
        "claim": "SAM does not establish mineral identity or abundance",
    }


def band_depth(spectrum: Spectrum, interval_um: tuple[float, float]):
    selected = (
        spectrum.valid
        & (spectrum.wavelength_um >= interval_um[0])
        & (spectrum.wavelength_um <= interval_um[1])
    )
    if not selected.any():
        return {"state": "insufficient_evidence", "band_center_um": None, "depth": None}
    indices = np.flatnonzero(selected)
    minimum = indices[np.argmin(spectrum.reflectance[selected])]
    return {
        "state": "candidate_absorption_only",
        "band_center_um": float(spectrum.wavelength_um[minimum]),
        "depth": float(1 - spectrum.reflectance[minimum]),
    }
