"""Body-aware intake and descriptive measurements of published Mars geology.

This module does not evaluate predicted contacts. A published contact's certainty
is a geological interpretation, not a registration error or an accuracy label.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import math
from pathlib import Path, PurePosixPath
import stat
import zipfile

import numpy as np
from pyproj import CRS, Transformer
import shapely
from shapely.geometry import LineString, Point, Polygon, box, mapping
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

MARS_RADIUS_M = 3_396_190.0
SOURCE_URL = "https://doi.org/10.3133/sim3464"


@dataclass(frozen=True)
class MarsWindow:
    id: str
    latitude: float
    longitude: float
    side_m: float = 20_000.0
    body: str = "Mars"
    radius_m: float = MARS_RADIUS_M

    def __post_init__(self):
        if self.body != "Mars" or self.radius_m != MARS_RADIUS_M:
            raise ValueError("SIM3464 requires Mars and its 3396190 m reference sphere")
        if not all(
            math.isfinite(v) for v in (self.latitude, self.longitude, self.side_m)
        ):
            raise ValueError("Window coordinates and side must be finite")
        if not -90 < self.latitude < 90 or not -180 <= self.longitude <= 360:
            raise ValueError(
                "Use planetocentric Mars latitude and east-positive longitude"
            )
        if not 0 < self.side_m <= 100_000:
            raise ValueError("The local Mars window side must be in (0, 100000] metres")

    @property
    def local_crs(self) -> CRS:
        return CRS.from_proj4(
            f"+proj=aeqd +lat_0={self.latitude} +lon_0={self.longitude} "
            f"+R={self.radius_m} +units=m +type=crs"
        )


@dataclass(frozen=True)
class VectorFeature:
    source_fid: int
    geometry: BaseGeometry
    attributes: dict


@dataclass(frozen=True)
class VectorLayer:
    name: str
    crs: CRS
    features: tuple[VectorFeature, ...]


def validate_mars_crs(crs: CRS) -> None:
    """Reject Earth CRS and angular/native-coordinate substitutions at intake."""
    if not crs.is_projected:
        raise ValueError("Native geological measurements require a projected Mars CRS")
    ellipsoid = crs.ellipsoid
    if (
        abs(ellipsoid.semi_major_metre - MARS_RADIUS_M) > 0.01
        or abs(ellipsoid.semi_minor_metre - MARS_RADIUS_M) > 0.01
        or any(abs(axis.unit_conversion_factor - 1.0) > 1e-12 for axis in crs.axis_info)
    ):
        raise ValueError(
            "CRS must use metres and the SIM3464 Mars sphere, not Earth EPSG:4326"
        )


def extract_reference_archive(
    archive: Path, destination: Path, expected_sha256: str
) -> dict:
    """Verify the archive and extract only GIS/CRS files after checking every path."""
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != expected_sha256:
        raise ValueError("SIM3464 archive SHA-256 does not match the declared source")
    destination = destination.resolve()
    selected = []
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            name = PurePosixPath(member.filename)
            if (
                name.is_absolute()
                or ".." in name.parts
                or "\\" in member.filename
                or ":" in member.filename
                or stat.S_ISLNK(member.external_attr >> 16)
            ):
                raise ValueError(f"Unsafe archive member: {member.filename}")
            target = destination.joinpath(*name.parts).resolve()
            if not target.is_relative_to(destination):
                raise ValueError("Archive member leaves the extraction directory")
            if (
                name.parts[:2]
                not in (
                    ("sim3464_JezeroNili_FINAL", "Geodatabase"),
                    ("sim3464_JezeroNili_FINAL", "CoordinateSystems"),
                )
                or member.is_dir()
            ):
                continue
            selected.append((member, target))
        if sum(member.file_size for member, _ in selected) > 100_000_000:
            raise ValueError("Unexpected SIM3464 vector extraction size")
        for member, target in selected:
            contents = bundle.read(member)  # Also verifies the ZIP member CRC.
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists() or target.read_bytes() != contents:
                target.write_bytes(contents)
    return {
        "archive_sha256": digest,
        "archive_members": len(bundle.infolist()),
        "extracted_members": len(selected),
        "extracted_bytes": sum(member.file_size for member, _ in selected),
        "selection": "Geodatabase and CoordinateSystems only; supplied raster basemaps not extracted",
    }


def read_vector_layer(path: Path, name: str) -> VectorLayer:
    """Read OGR arrays directly, without requiring GeoPandas."""
    import pyogrio

    meta, fids, geometries, arrays = pyogrio.raw.read(
        path, layer=name, return_fids=True
    )
    crs = CRS.from_user_input(meta["crs"])
    validate_mars_crs(crs)
    decoded = shapely.from_wkb(geometries)
    records = []
    for i, (fid, geometry) in enumerate(zip(fids, decoded)):
        if geometry is None or geometry.is_empty:
            raise ValueError(f"Missing geometry in {name}, FID {fid}")
        properties = {}
        for field, values in zip(meta["fields"], arrays):
            value = values[i]
            if isinstance(value, np.generic):
                value = value.item()
            if isinstance(value, float) and not math.isfinite(value):
                value = None
            properties[str(field)] = value
        records.append(VectorFeature(int(fid), geometry, properties))
    return VectorLayer(name, crs, tuple(records))


def contact_category(value: str) -> str:
    if value not in {"certain", "approximate", "inferred", "boundary"}:
        raise ValueError(f"Undeclared geological contact type: {value!r}")
    return value


def repair_units_for_analysis(layer: VectorLayer) -> tuple[VectorLayer, list[dict]]:
    """Keep native originals intact; document any make_valid analytical copies."""
    repaired, changes = [], []
    for feature in layer.features:
        geometry = feature.geometry
        if not geometry.is_valid:
            valid = shapely.make_valid(geometry)
            changes.append(
                {
                    "source_fid": feature.source_fid,
                    "reason": shapely.is_valid_reason(geometry),
                    "method": "shapely.make_valid on analytical copy only",
                    "original_area_m2": geometry.area,
                    "analytical_area_m2": valid.area,
                    "area_change_m2": valid.area - geometry.area,
                    "analytical_geometry_type": valid.geom_type,
                }
            )
            geometry = valid
        repaired.append(VectorFeature(feature.source_fid, geometry, feature.attributes))
    return VectorLayer(layer.name, layer.crs, tuple(repaired)), changes


def window_footprint(window: MarsWindow, destination_crs: CRS) -> BaseGeometry:
    """Densify edges to 100 m before projecting the local 20 km square."""
    half = window.side_m / 2
    axis = np.linspace(-half, half, math.ceil(window.side_m / 100) + 1)
    vertices = (
        [(float(x), -half) for x in axis]
        + [(half, float(y)) for y in axis[1:]]
        + [(float(x), half) for x in axis[-2::-1]]
        + [(-half, float(y)) for y in axis[-2:0:-1]]
    )
    conversion = Transformer.from_crs(window.local_crs, destination_crs, always_xy=True)
    return shapely.transform(Polygon(vertices), conversion.transform, interleaved=False)


def characterize_window(
    window: MarsWindow, boundary: VectorLayer, contacts: VectorLayer, units: VectorLayer
) -> tuple[dict, VectorLayer, VectorLayer]:
    """Measure the observed map within a local support, retaining certainty types."""
    local = window.local_crs
    half = window.side_m / 2
    support = box(-half, -half, half, half)
    to_local = Transformer.from_crs(boundary.crs, local, always_xy=True)
    map_polygon = unary_union(
        [
            shapely.transform(f.geometry, to_local.transform, interleaved=False)
            for f in boundary.features
        ]
    )
    observed = support.intersection(map_polygon)
    mapped_area = observed.area
    summary = {
        "id": window.id,
        "body": window.body,
        "latitude": window.latitude,
        "longitude_east": window.longitude,
        "latitude_convention": "planetocentric",
        "body_radius_m": window.radius_m,
        "side_m": window.side_m,
        "support_area_km2": support.area / 1e6,
        "analysis_crs_wkt": local.to_wkt(),
        "map_coverage_fraction": mapped_area / support.area,
        "mapped_area_km2": mapped_area / 1e6,
        "center_to_map_distance_km": Point(0, 0).distance(map_polygon) / 1000,
        "source_url": SOURCE_URL,
    }
    if mapped_area <= 0:
        summary.update(
            {
                "status": "outside_acquired_reference_coverage",
                "unit_class_count": None,
                "unit_classes": None,
                "contacts": None,
                "transects": None,
                "interpretation": "No SIM3464 reference coverage. Contact absence and target geology are unknown.",
            }
        )
        return (
            summary,
            VectorLayer(units.name, local, ()),
            VectorLayer(contacts.name, local, ()),
        )

    clipped_units, clipped_contacts = [], []
    by_symbol = defaultdict(
        lambda: {"area_km2": 0.0, "polygon_feature_count": 0, "source_names": set()}
    )
    unit_transform = Transformer.from_crs(units.crs, local, always_xy=True)
    for feature in units.features:
        clipped = shapely.transform(
            feature.geometry, unit_transform.transform, interleaved=False
        ).intersection(observed)
        if clipped.area <= 0:
            continue
        clipped_units.append(
            VectorFeature(feature.source_fid, clipped, feature.attributes)
        )
        entry = by_symbol[feature.attributes["symbol"]]
        entry["area_km2"] += clipped.area / 1e6
        entry["polygon_feature_count"] += 1
        entry["source_names"].add(feature.attributes["name"])

    source_types = sorted(
        {contact_category(f.attributes["TYPE"]) for f in contacts.features}
        - {"boundary"}
    )
    contact_stats = {
        kind: {"source_feature_count": 0, "length_km": 0.0} for kind in source_types
    }
    excluded_boundary = {"source_feature_count": 0, "length_km": 0.0}
    contact_transform = Transformer.from_crs(contacts.crs, local, always_xy=True)
    for feature in contacts.features:
        kind = contact_category(feature.attributes["TYPE"])
        clipped = shapely.transform(
            feature.geometry, contact_transform.transform, interleaved=False
        ).intersection(observed)
        if clipped.length <= 0:
            continue
        clipped_contacts.append(
            VectorFeature(feature.source_fid, clipped, feature.attributes)
        )
        if kind == "boundary":
            excluded_boundary["source_feature_count"] += 1
            excluded_boundary["length_km"] += clipped.length / 1000
            continue
        contact_stats[kind]["source_feature_count"] += 1
        contact_stats[kind]["length_km"] += clipped.length / 1000
    length = sum(v["length_km"] for v in contact_stats.values())
    classes = []
    for symbol, entry in sorted(by_symbol.items()):
        classes.append(
            {
                "symbol": symbol,
                **entry,
                "source_names": sorted(entry["source_names"]),
                "fraction_of_support": entry["area_km2"] / (support.area / 1e6),
            }
        )
    area_sum = sum(feature.geometry.area for feature in clipped_units)
    covered_units = unary_union([feature.geometry for feature in clipped_units])

    transects = []
    for name, line in (
        ("west_to_east", LineString([(-half, 0), (half, 0)])),
        ("south_to_north", LineString([(0, -half), (0, half)])),
    ):
        points, overlapping = {}, []
        for feature in clipped_contacts:
            if feature.attributes["TYPE"] == "boundary":
                continue
            crossing = line.intersection(feature.geometry)
            if crossing.is_empty:
                continue
            if crossing.length > 0:
                overlapping.append(feature.source_fid)
            geometries = (
                list(crossing.geoms) if hasattr(crossing, "geoms") else [crossing]
            )
            for geometry in geometries:
                if geometry.geom_type != "Point":
                    continue
                distance = round(line.project(geometry), 6)
                entry = points.setdefault(
                    distance, {"source_fids": [], "contact_types": set()}
                )
                entry["source_fids"].append(feature.source_fid)
                entry["contact_types"].add(feature.attributes["TYPE"])
        transects.append(
            {
                "id": name,
                "length_km": line.length / 1000,
                "distinct_point_intersections": len(points),
                "crossings": [
                    {
                        "distance_from_start_m": distance,
                        "source_fids": entry["source_fids"],
                        "contact_types": sorted(entry["contact_types"]),
                    }
                    for distance, entry in sorted(points.items())
                ],
                "overlapping_source_fids": overlapping,
                "interpretation": "Geometric intersections of existing linework, not field-verified transitions or mapping performance.",
            }
        )
    summary.update(
        {
            "status": "calibration_characterization",
            "unit_class_count": len(classes),
            "unit_classes": classes,
            "unit_polygon_feature_count": len(clipped_units),
            "unit_area_sum_km2": area_sum / 1e6,
            "unit_union_area_km2": covered_units.area / 1e6,
            "unit_overlap_area_km2": (area_sum - covered_units.area) / 1e6,
            "unit_gap_within_map_km2": observed.difference(covered_units).area / 1e6,
            "contacts": {
                "by_certainty": contact_stats,
                "total_length_km": length,
                "source_feature_count": sum(
                    v["source_feature_count"] for v in contact_stats.values()
                ),
                "density_km_per_mapped_km2": length / (mapped_area / 1e6),
                "excluded_map_frame_boundary": excluded_boundary,
                "interpretation": "Mapped line length divided by mapped area; not physical fracture density or contact accuracy.",
            },
            "transects": transects,
        }
    )
    return (
        summary,
        VectorLayer(units.name, local, tuple(clipped_units)),
        VectorLayer(contacts.name, local, tuple(clipped_contacts)),
    )


def export_native_geopackage(path: Path, layers: tuple[VectorLayer, ...]) -> None:
    """Preserve original GIS attributes, geometries and source feature identifiers."""
    import pyogrio

    if path.exists():
        path.unlink()
    for layer in layers:
        fields = ["source_fid", *layer.features[0].attributes, "source_url", "body"]
        arrays = [
            np.array([feature.source_fid for feature in layer.features], dtype=np.int64)
        ]
        for field in layer.features[0].attributes:
            values = [feature.attributes[field] for feature in layer.features]
            nonnull = [value for value in values if value is not None]
            dtype = (
                float
                if nonnull and all(isinstance(value, (float, int)) for value in nonnull)
                else object
            )
            arrays.append(np.array(values, dtype=dtype))
        arrays.extend(
            [
                np.full(len(layer.features), SOURCE_URL, dtype=object),
                np.full(len(layer.features), "Mars", dtype=object),
            ]
        )
        pyogrio.raw.write(
            path,
            shapely.to_wkb([feature.geometry for feature in layer.features]),
            arrays,
            fields=fields,
            layer=layer.name,
            driver="GPKG",
            crs=layer.crs.to_wkt(),
            geometry_type="Unknown",
            promote_to_multi=False,
            dataset_metadata={
                "source": SOURCE_URL,
                "body": "Mars",
                "role": "calibration reference",
            },
        )


def mars_geojson(window: MarsWindow, layers: tuple[VectorLayer, ...]) -> dict:
    """Return explicitly non-RFC7946 Mars GeoJSON, never WGS84/Earth coordinates."""
    geographic = CRS.from_proj4(f"+proj=longlat +R={window.radius_m} +type=crs")
    features = []
    footprint = window_footprint(window, geographic)
    features.append(
        {
            "type": "Feature",
            "geometry": mapping(footprint),
            "properties": {
                "kind": "analysis_support",
                "id": window.id,
                "side_m": window.side_m,
                "body": "Mars",
                "source_url": SOURCE_URL,
            },
        }
    )
    for layer in layers:
        conversion = Transformer.from_crs(layer.crs, geographic, always_xy=True)
        for feature in layer.features:
            features.append(
                {
                    "type": "Feature",
                    "geometry": mapping(
                        shapely.transform(
                            feature.geometry, conversion.transform, interleaved=False
                        )
                    ),
                    "properties": {
                        **feature.attributes,
                        "source_fid": feature.source_fid,
                        "source_layer": layer.name,
                        "source_url": SOURCE_URL,
                        "body": "Mars",
                        "role": "calibration_reference",
                    },
                }
            )
    return {
        "type": "FeatureCollection",
        "name": "SIM3464 Jezero 20 km calibration",
        "crs": {"type": "name", "properties": {"name": "Mars_2000_Sphere_R3396190"}},
        "coordinate_system": {
            "body": "Mars",
            "radius_m": window.radius_m,
            "axes": [
                "east-positive longitude degrees",
                "planetocentric latitude degrees",
            ],
            "wkt": geographic.to_wkt(),
            "rfc7946": False,
            "warning": "Planetary GeoJSON. Do not load as Earth EPSG:4326 or an Earth web map.",
        },
        "reference_policy": {
            "publication_scale": 75000,
            "registration_offset_m": [100, 200],
            "geological_tolerance_m": None,
            "blind_target_truth": False,
            "automatic_accuracy_assessment_allowed": False,
        },
        "features": features,
    }
