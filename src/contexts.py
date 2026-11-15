"""Unweighted environmental context with explicit physical quantities and masks."""

from typing import Literal
from pydantic import BaseModel, Field
import numpy as np


class ContextMetadata(BaseModel):
    source_id: str
    source_url: str
    body: Literal["Earth", "Mars", "Moon"]
    quantity: Literal[
        "surface_temperature", "air_temperature", "thermal_inertia", "albedo"
    ]
    units: Literal["K", "J m-2 K-1 s-1/2", "fraction"]
    observation_time: str
    local_solar_time: str
    season_or_solar_longitude: str
    retrieval_model: str
    nominal_spacing_m: float = Field(gt=0, allow_inf_nan=False)
    quality_rule: str


def summarize_context(values: np.ndarray, valid: np.ndarray, metadata: ContextMetadata):
    expected_units = {
        "surface_temperature": "K",
        "air_temperature": "K",
        "thermal_inertia": "J m-2 K-1 s-1/2",
        "albedo": "fraction",
    }
    if metadata.units != expected_units[metadata.quantity]:
        raise ValueError("Units do not match the physical context quantity")
    if values.shape != valid.shape or valid.dtype != bool:
        raise ValueError("Context array and boolean quality mask must align")
    good = valid & np.isfinite(values)
    measurements = values[good]
    if measurements.size and (
        np.any(measurements < 0)
        or metadata.quantity == "albedo"
        and np.any(measurements > 1)
    ):
        raise ValueError("Context values violate physical bounds")
    return {
        "state": "measured_context" if good.any() else "insufficient_evidence",
        "metadata": metadata.model_dump(),
        "valid_fraction": float(good.mean()),
        "median": float(np.median(measurements)) if good.any() else None,
        "p10": float(np.percentile(measurements, 10)) if good.any() else None,
        "p90": float(np.percentile(measurements, 90)) if good.any() else None,
        "role": "unweighted_context_only",
        "excluded_inferences": [
            "An instantaneous temperature is not thermal inertia",
            "Earth context cannot reproduce lunar vacuum, pressure, gravity or radiation",
            "Context never changes terrain loss or mandatory-evidence gates",
        ],
    }
