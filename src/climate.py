"""Source-valid climate observations and a terrain-independent spatial frame."""

from collections import Counter
from collections.abc import Callable
import math
import re

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pyproj import Geod, Transformer
import rasterio
from rasterio.windows import from_bounds

GEOD = Geod(ellps="WGS84")
TO_EQUAL_AREA = Transformer.from_crs(4326, 6933, always_xy=True)
FROM_EQUAL_AREA = Transformer.from_crs(6933, 4326, always_xy=True)


class ClimateStratum(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    symbol: str
    count: int = Field(gt=0)


class SamplingDesign(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    seed: int = Field(ge=0)
    maximum_attempts: int = Field(gt=0)
    proposal_crs: str
    nasadem_latitude_bounds: tuple[float, float]
    context_m: float = Field(gt=0, allow_inf_nan=False)
    ai_maximum: float = Field(ge=0, allow_inf_nan=False)
    strata: tuple[ClimateStratum, ...]

    @model_validator(mode="after")
    def validate_domain(self):
        south, north = self.nasadem_latitude_bounds
        if not -56 <= south < north <= 60 or self.proposal_crs != "EPSG:6933":
            raise ValueError("The frame requires EPSG:6933 and the NASADEM latitude band")
        symbols = [s.symbol for s in self.strata]
        if not symbols or len(set(symbols)) != len(symbols) or not set(symbols) <= {"BWh", "BWk"}:
            raise ValueError("Declare distinct BWh/BWk strata")
        return self


def parse_koppen_legend(text: str) -> dict[int, dict]:
    """Read symbols from the supplied legend instead of guessing numeric classes."""
    matches = re.findall(
        r"^\s*(\d+):\s+(\w+)\s+(.+?)\s+\[(\d+)\s+(\d+)\s+(\d+)\]", text, re.M
    )
    result = {
        int(code): {"symbol": symbol, "description": description, "rgb": [int(r), int(g), int(b)]}
        for code, symbol, description, r, g, b in matches
    }
    if len(result) != len(matches) or not {"BWh", "BWk"} <= {v["symbol"] for v in result.values()}:
        raise ValueError("The source legend must declare unique codes including BWh and BWk")
    return result


class ClimateRasters:
    """Three already opened sources, validated once at their ingestion boundary."""

    def __init__(self, ai, et0, koppen, legend: dict[int, dict]):
        self.ai, self.et0, self.koppen, self.legend = ai, et0, koppen, legend
        for source in (ai, et0, koppen):
            if source.crs != rasterio.crs.CRS.from_epsg(4326) or source.count != 1:
                raise ValueError("Climate sources must be single-band geographic WGS84 rasters")
        if ai.shape != et0.shape or not ai.transform.almost_equals(et0.transform):
            raise ValueError("Annual AI and ET0 must share their native grid")
        if not ai.transform.almost_equals(koppen.transform):
            raise ValueError("The declared historical climate map must align with the annual grid")
        if et0.nodata != 65535 or koppen.nodata != 0:
            raise ValueError("Unexpected source nodata metadata; inspect the new release before use")

    def points(self, coordinates: np.ndarray) -> list[dict]:
        results = []
        values = [list(source.sample(coordinates, masked=True)) for source in (self.ai, self.et0, self.koppen)]
        for point, ai, et0, koppen in zip(coordinates, *values):
            lon, lat = point
            annual_inside = self.ai.bounds.left <= lon < self.ai.bounds.right and self.ai.bounds.bottom < lat <= self.ai.bounds.top
            climate_inside = self.koppen.bounds.left <= lon < self.koppen.bounds.right and self.koppen.bounds.bottom < lat <= self.koppen.bounds.top
            annual_valid = annual_inside and not np.ma.is_masked(et0[0]) and np.isfinite(et0[0]) and et0[0] > 0
            ai_valid = annual_valid and not np.ma.is_masked(ai[0]) and np.isfinite(ai[0]) and ai[0] >= 0
            koppen_valid = climate_inside and not np.ma.is_masked(koppen[0]) and np.isfinite(koppen[0]) and koppen[0] == int(koppen[0]) and int(koppen[0]) in self.legend
            code = int(koppen[0]) if koppen_valid else None
            results.append({
                "ai_raw": int(ai[0]) if annual_inside and not np.ma.is_masked(ai[0]) and np.isfinite(ai[0]) else None,
                "ai_ratio": float(ai[0]) * 0.0001 if ai_valid else None,
                "et0_mm_year": float(et0[0]) if annual_valid else None,
                "koppen_code": code,
                "koppen_symbol": self.legend[code]["symbol"] if koppen_valid else None,
                "state": "modelled_climate_observation" if ai_valid and koppen_valid else "missing_climate_support",
            })
        return results

    def region_summary(self, bbox: list[float], ai_maximum: float) -> dict:
        """Native pixel summaries with ellipsoidal equal-area row weights."""
        window = from_bounds(*bbox, self.ai.transform).round_offsets().round_lengths()
        ai = self.ai.read(1, window=window, masked=True)
        et0 = self.et0.read(1, window=window, masked=True)
        koppen = self.koppen.read(1, window=window, masked=True)
        valid = (~np.ma.getmaskarray(et0)) & np.isfinite(et0) & (np.asarray(et0) > 0) & (~np.ma.getmaskarray(ai)) & np.isfinite(ai) & (np.asarray(ai) >= 0)
        ai_values = np.asarray(ai, dtype=float) * 0.0001
        kg = np.asarray(koppen)
        class_codes = [code for code, item in self.legend.items() if item["symbol"] in {"BWh", "BWk"}]
        joint = valid & (~np.ma.getmaskarray(koppen)) & np.isin(kg, list(self.legend))
        dry = joint & (ai_values <= ai_maximum) & np.isin(kg, class_codes)
        transform = self.ai.window_transform(window)
        edges = transform.f + np.arange(ai.shape[0] + 1) * transform.e
        _, ys = TO_EQUAL_AREA.transform(np.zeros_like(edges), edges)
        x0, _ = TO_EQUAL_AREA.transform(transform.c, 0)
        x1, _ = TO_EQUAL_AREA.transform(transform.c + transform.a, 0)
        weights = np.broadcast_to((np.abs(np.diff(ys)) * (x1 - x0))[:, None], ai.shape)
        total = float(weights.sum())
        observed_area = float(weights[valid].sum())
        return {
            "support": "All native 30 arcsecond pixels in the declared region bounding box; EPSG:6933 ellipsoidal area weights",
            "bbox": bbox,
            "native_pixel_count": int(ai.size),
            "annual_observed_pixel_count": int(valid.sum()),
            "bbox_area_km2": total / 1e6,
            "annual_valid_area_fraction": observed_area / total,
            "joint_valid_area_fraction": float(weights[joint].sum() / total),
            "dry_desert_area_fraction": float(weights[dry].sum() / total),
            "ai_area_weighted_mean": float(np.sum(weights[valid] * ai_values[valid]) / observed_area) if observed_area else None,
            "et0_area_weighted_mean_mm_year": float(np.sum(weights[valid] * np.asarray(et0)[valid]) / observed_area) if observed_area else None,
            "koppen_area_fraction": {
                item["symbol"]: float(weights[(kg == code) & (~np.ma.getmaskarray(koppen))].sum() / total)
                for code, item in self.legend.items() if np.any(kg == code)
            },
        }


def equal_area_proposals(design: SamplingDesign) -> np.ndarray:
    south, north = design.nasadem_latitude_bounds
    west_x, south_y = TO_EQUAL_AREA.transform(-180, south)
    east_x, north_y = TO_EQUAL_AREA.transform(180, north)
    uv = np.random.Generator(np.random.PCG64(design.seed)).random((design.maximum_attempts, 2))
    xs = west_x + uv[:, 0] * (east_x - west_x)
    ys = south_y + uv[:, 1] * (north_y - south_y)
    lon, lat = FROM_EQUAL_AREA.transform(xs, ys)
    return np.column_stack([lon, lat])


def context_envelope(longitude: float, latitude: float, context_m: float) -> list[float]:
    """Conservative bbox of the square's enclosing geodesic disk, not its footprint."""
    radius = context_m / math.sqrt(2)
    # The global minimum WGS84 meridional radius bounds latitude travel. N >= a
    # then bounds longitude travel anywhere within that latitude envelope.
    latitude_margin = math.degrees(radius / 6335439.0)
    max_latitude = abs(latitude) + latitude_margin
    longitude_margin = math.degrees(radius / (6378137.0 * math.cos(math.radians(max_latitude))))
    return [longitude - longitude_margin, latitude - latitude_margin, longitude + longitude_margin, latitude + latitude_margin]


def context_polygon(longitude: float, latitude: float, context_m: float) -> dict:
    half = context_m / 2
    edge = np.linspace(-half, half, 41)
    xs = np.concatenate([edge, np.full(40, half), edge[-2::-1], np.full(39, -half), [-half]])
    ys = np.concatenate([np.full(41, -half), edge[1:], np.full(40, half), edge[-2:0:-1], [-half]])
    azimuth = np.degrees(np.arctan2(xs, ys))
    lon, lat, _ = GEOD.fwd(np.full(xs.size, longitude), np.full(xs.size, latitude), azimuth, np.hypot(xs, ys))
    return {"type": "Polygon", "coordinates": [np.column_stack([lon, lat]).tolist()]}


def nasadem_tiles(bbox: list[float]) -> list[str]:
    west, south, east, north = bbox
    if not -180 <= west < east <= 180 or not -56 <= south < north <= 60:
        raise ValueError("NASADEM acquisition bbox must stay inside the declared coverage band")
    return [
        f"{'n' if lat >= 0 else 's'}{abs(lat):02d}{'e' if lon >= 0 else 'w'}{abs(lon):03d}"
        for lat in range(math.floor(south), math.ceil(north))
        for lon in range(math.floor(west), math.ceil(east))
    ]


def freeze_frame(
    design: SamplingDesign,
    observe: Callable[[np.ndarray], list[dict]],
    controls: list[dict],
) -> dict:
    proposals = equal_area_proposals(design)
    quotas = {s.symbol: s.count for s in design.strata}
    counts = Counter({symbol: 0 for symbol in quotas})
    accepted, attempts = [], []
    separation = math.sqrt(2) * design.context_m
    south, north = design.nasadem_latitude_bounds
    for offset in range(0, len(proposals), 512):
        points = proposals[offset:offset + 512]
        observations = observe(points)
        if len(observations) != len(points):
            raise ValueError("The climate observer must return one record per proposal")
        for number, point, observation in zip(range(offset + 1, offset + 1 + len(points)), points, observations):
            longitude, latitude = map(float, point)
            bbox = context_envelope(longitude, latitude, design.context_m)
            symbol = observation["koppen_symbol"]
            if bbox[1] < south or bbox[3] > north:
                reason = "outside_nasadem_context_latitude"
            elif bbox[0] < -180 or bbox[2] > 180:
                reason = "antimeridian_context"
            elif observation["et0_mm_year"] is None:
                reason = "missing_et0"
            elif observation["ai_ratio"] is None:
                reason = "missing_ai"
            elif observation["ai_ratio"] > design.ai_maximum:
                reason = "ai_above_threshold"
            elif symbol is None:
                reason = "missing_koppen"
            elif symbol not in quotas:
                reason = "koppen_not_selected_desert_class"
            elif counts[symbol] >= quotas[symbol]:
                reason = "stratum_quota_already_filled"
            elif any(GEOD.inv(longitude, latitude, c["longitude"], c["latitude"])[2] < separation for c in controls):
                reason = "known_control_context_overlap"
            elif any(GEOD.inv(longitude, latitude, c["longitude"], c["latitude"])[2] < separation for c in accepted):
                reason = "sampled_context_overlap"
            else:
                reason = "accepted"
                polygon = context_polygon(longitude, latitude, design.context_m)
                ring = np.asarray(polygon["coordinates"][0])
                area, _ = GEOD.polygon_area_perimeter(ring[:, 0], ring[:, 1])
                accepted.append({
                    "id": f"GLOBAL-{len(accepted) + 1:04d}",
                    "proposal_number": number,
                    "longitude": longitude,
                    "latitude": latitude,
                    "stratum": symbol,
                    "center_climate": observation,
                    "context_m": design.context_m,
                    "nominal_area_km2": design.context_m ** 2 / 1e6,
                    "ellipsoidal_polygon_area_km2": abs(area) / 1e6,
                    "geometry": polygon,
                    "bbox": [float(ring[:, 0].min()), float(ring[:, 1].min()), float(ring[:, 0].max()), float(ring[:, 1].max())],
                    "acquisition_bbox": bbox,
                    "nasadem_tiles": nasadem_tiles(bbox),
                    "terrain_status": "not_acquired_or_measured_by_this_frame",
                })
                counts[symbol] += 1
            attempts.append({"proposal_number": number, "longitude": longitude, "latitude": latitude, **observation, "reason": reason})
            if all(counts[symbol] == count for symbol, count in quotas.items()):
                return {"blocks": accepted, "attempts": attempts, "stratum_counts": dict(counts), "unfilled_count": 0}
    return {"blocks": accepted, "attempts": attempts, "stratum_counts": dict(counts), "unfilled_count": sum(quotas.values()) - len(accepted)}


def summarize_context(block: dict, rasters: ClimateRasters, spacing_m: int, ai_maximum: float) -> dict:
    if not 0 < spacing_m <= block["context_m"]:
        raise ValueError("Context summary spacing must be positive and no larger than the context")
    count = int(block["context_m"] / spacing_m)
    edges = (np.arange(count) + 0.5) * block["context_m"] / count - block["context_m"] / 2
    xs, ys = np.meshgrid(edges, edges)
    lon, lat, _ = GEOD.fwd(
        np.full(xs.size, block["longitude"]), np.full(xs.size, block["latitude"]),
        np.degrees(np.arctan2(xs, ys)).ravel(), np.hypot(xs, ys).ravel(),
    )
    observations = rasters.points(np.column_stack([lon, lat]))
    annual = [o for o in observations if o["ai_ratio"] is not None]
    joint = [o for o in annual if o["koppen_symbol"] is not None]
    dry = [o for o in joint if o["ai_ratio"] <= ai_maximum and o["koppen_symbol"] in {"BWh", "BWk"}]
    return {
        "support": f"Descriptive {count} by {count} grid in the local AEQD context, approximately {spacing_m} m spacing; not a native-pixel area census or an eligibility gate",
        "sample_count": len(observations),
        "annual_valid_fraction": len(annual) / len(observations),
        "joint_valid_fraction": len(joint) / len(observations),
        "dry_desert_fraction": len(dry) / len(observations),
        "ai_mean": float(np.mean([o["ai_ratio"] for o in annual])) if annual else None,
        "et0_mean_mm_year": float(np.mean([o["et0_mm_year"] for o in annual])) if annual else None,
        "koppen_counts": dict(sorted(Counter(o["koppen_symbol"] for o in joint).items())),
        "changes_sample_membership": False,
    }
