"""Body-specific source boundaries and masked, metric terrain descriptors."""

from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from pyproj import CRS, Transformer
from scipy.ndimage import map_coordinates, gaussian_filter, binary_erosion

SLOPE_EDGES = np.array([0, 1, 2, 3, 5, 8, 12, 20, 35, 60, 90], dtype=float)
SLOPE_CENTERS = (SLOPE_EDGES[:-1] + SLOPE_EDGES[1:]) / 2


@dataclass
class Raster:
    id: str
    values: np.ndarray
    west: float
    north: float
    ppd: int
    scale: float
    radius: float | None
    node_registered: bool = False
    water: np.ndarray | None = None

    def sample(self, longitude: np.ndarray, latitude: np.ndarray) -> np.ndarray:
        lon = longitude % 360 if self.radius else longitude
        offset = 0 if self.node_registered else 0.5
        rows = (self.north - latitude) * self.ppd - offset
        cols = (lon - self.west) * self.ppd - offset
        # Longitude periodicity belongs to a full-globe source, not partial MOLA tiles.
        periodic = self.values.shape[1] == 360 * self.ppd
        if periodic:
            cols %= self.values.shape[1]
        r0 = max(0, int(np.floor(rows.min())) - 1)
        r1 = min(self.values.shape[0], int(np.ceil(rows.max())) + 2)
        c0 = int(np.floor(cols.min())) - 1
        c1 = int(np.ceil(cols.max())) + 2
        if periodic:
            padded = self.values[r0:r1, np.arange(c0, c1) % self.values.shape[1]]
        else:
            c0, c1 = max(0, c0), min(self.values.shape[1], c1)
            padded = self.values[r0:r1, c0:c1]
        valid = (padded != -32768).astype(float)
        if self.water is not None:
            valid *= self.water[r0:r1, c0:c1] != 255
        raw = np.where(valid, padded, 0).astype(float) * self.scale
        coordinates = [rows - r0, cols - c0]
        weight = map_coordinates(valid, coordinates, order=1, mode="constant", cval=0)
        values = map_coordinates(raw, coordinates, order=1, mode="constant", cval=0)
        return np.where(weight > 0.999, values, np.nan)


def open_nasadem(directory: Path) -> Raster:
    path = directory / "s24w069.hgt"
    if path.stat().st_size != 3601 * 3601 * 2:
        raise ValueError("NASADEM source size does not match a 3601 square int16 tile")
    values = np.memmap(path, dtype=">i2", mode="r", shape=(3601, 3601))
    # NASADEM SWB: 0 land, 255 water. NUM records ancestry, not a binary validity flag.
    water = np.memmap(
        directory / "s24w069.swb", dtype="u1", mode="r", shape=(3601, 3601)
    )
    return Raster("nasadem", values, -69, -23, 3600, 1, None, True, water)


def open_nasadem_mosaic(root: Path, tiles: list[str], output: Path) -> Raster:
    """Join complete node-registered tiles without duplicating boundary nodes."""
    definitions = []
    for name in tiles:
        if (
            len(name) != 7
            or name[0] not in "ns"
            or name[3] not in "ew"
            or not name[1:3].isdigit()
            or not name[4:].isdigit()
        ):
            raise ValueError(f"Invalid NASADEM tile identifier: {name}")
        south = int(name[1:3]) * (-1 if name[0] == "s" else 1)
        west = int(name[4:]) * (-1 if name[3] == "w" else 1)
        directory = root / f"NASADEM_HGT_{name}"
        for suffix, size in [("hgt", 3601 * 3601 * 2), ("swb", 3601 * 3601)]:
            if (directory / f"{name}.{suffix}").stat().st_size != size:
                raise ValueError(f"Incomplete NASADEM tile {name}.{suffix}")
        definitions.append((name, south, west, directory))
    west = min(d[2] for d in definitions)
    east = max(d[2] for d in definitions) + 1
    south = min(d[1] for d in definitions)
    north = max(d[1] for d in definitions) + 1
    shape = ((north - south) * 3600 + 1, (east - west) * 3600 + 1)
    output.parent.mkdir(parents=True, exist_ok=True)
    z = np.memmap(output, dtype=">i2", mode="w+", shape=shape)
    z[:] = -32768
    water = np.memmap(output.with_suffix(".swb"), dtype="u1", mode="w+", shape=shape)
    water[:] = 255
    for name, tile_south, tile_west, directory in definitions:
        row = (north - tile_south - 1) * 3600
        col = (tile_west - west) * 3600
        z[row : row + 3601, col : col + 3601] = np.memmap(
            directory / f"{name}.hgt", dtype=">i2", mode="r", shape=(3601, 3601)
        )
        water[row : row + 3601, col : col + 3601] = np.memmap(
            directory / f"{name}.swb", dtype="u1", mode="r", shape=(3601, 3601)
        )
    z.flush()
    water.flush()
    return Raster("nasadem", z, west, north, 3600, 1, None, True, water)


def open_pds(path: Path, label: Path, kind: str) -> Raster:
    tree = ET.parse(label)
    ns = {"p": "http://pds.nasa.gov/pds4/pds/v1"}
    image = tree.find(".//p:Array_2D_Image", ns)
    if image is None:
        raise ValueError(f"No PDS image definition in {label}")
    shape = tuple(
        int(a.findtext("p:elements", namespaces=ns))
        for a in image.findall("p:Axis_Array", ns)
    )
    data_type = image.findtext("p:Element_Array/p:data_type", namespaces=ns)
    if data_type not in {"SignedMSB2", "SignedLSB2"} or len(shape) != 2:
        raise ValueError("Unsupported PDS raster encoding")
    if path.stat().st_size != int(np.prod(shape)) * 2:
        raise ValueError(f"Incomplete {kind} raster; run scripts/acquire.py")
    values = np.memmap(
        path, dtype=">i2" if data_type == "SignedMSB2" else "<i2", mode="r", shape=shape
    )
    if kind == "mola":
        if shape != (5632, 11520):
            raise ValueError("MOLA label does not match the declared 44N/0E tile")
        return Raster(kind, values, 0, 44, 128, 1, 3396000)
    if shape != (11520, 23040):
        raise ValueError("LOLA label does not match the declared global 64 ppd product")
    scale = float(image.findtext("p:Element_Array/p:scaling_factor", namespaces=ns))
    # PDS label: height = DN * 0.5. The 1737400 offset defines radius, not height.
    return Raster(kind, values, 0, 90, 64, scale, 1737400)


def project_window(source: Raster, lat: float, lon: float, extent_m: int, step_m: int):
    """AEQD centered on the study window; planetary CRS never uses Earth defaults."""
    shape = "+datum=WGS84" if source.radius is None else f"+R={source.radius}"
    local = CRS.from_proj4(f"+proj=aeqd +lat_0={lat} +lon_0={lon} {shape} +units=m")
    geographic = CRS.from_proj4(f"+proj=longlat {shape}")
    inverse = Transformer.from_crs(local, geographic, always_xy=True)
    axis = np.arange(-extent_m / 2 + step_m / 2, extent_m / 2, step_m)
    x, y = np.meshgrid(axis, -axis)
    longitude, latitude = inverse.transform(x, y)
    return source.sample(longitude, latitude), inverse


def smooth_grid(z: np.ndarray, source_step: int, support: int) -> np.ndarray:
    """Gaussian FWHM = analysis spacing; masked weights must exceed .999."""
    sigma = support / (2.355 * source_step)
    valid = np.isfinite(z)
    weight = gaussian_filter(valid.astype(float), sigma, mode="constant", cval=0)
    numerator = gaussian_filter(np.nan_to_num(z), sigma, mode="constant", cval=0)
    return np.where(weight > 0.999, numerator / np.maximum(weight, 1e-12), np.nan)


def features(
    context: np.ndarray, spacing: int, minimum: float = 0.95, erode: bool = False
):
    n = 20000 // spacing
    start = (context.shape[0] - n) // 2
    local = context[start : start + n, start : start + n].copy()
    context_valid = np.isfinite(context)
    if np.mean(context_valid) < minimum or np.mean(np.isfinite(local)) < minimum:
        return None
    valid = np.isfinite(local)
    if erode:
        valid = binary_erosion(valid, iterations=1, border_value=0)
    # Erode every derivative stencil; invalid neighbors never become zero elevation.
    derivative_valid = binary_erosion(valid, iterations=1, border_value=0)
    dy, dx = np.gradient(local, spacing)
    slopes = np.degrees(np.arctan(np.hypot(dx, dy)))[derivative_valid]
    if not len(slopes):
        return None
    hist = np.histogram(slopes, bins=SLOPE_EDGES)[0].astype(float)
    hist /= hist.sum()
    local_values = local[valid]
    yy, xx = np.indices(local.shape)
    design = np.column_stack(
        [xx[valid] * spacing, yy[valid] * spacing, np.ones(valid.sum())]
    )
    fit = np.linalg.lstsq(design, local_values, rcond=None)[0]
    residual = local_values - design @ fit
    gradient = np.column_stack([dx[derivative_valid], dy[derivative_valid]])
    eigen = np.linalg.eigvalsh(gradient.T @ gradient / len(gradient))
    anisotropy = (
        float((eigen[-1] - eigen[0]) / eigen.sum()) if eigen.sum() > 1e-12 else 0.0
    )
    sigma = 2000 / spacing
    numerator = gaussian_filter(np.nan_to_num(local), sigma)
    weight = gaussian_filter(np.isfinite(local).astype(float), sigma)
    tpi = local - numerator / np.maximum(weight, 1e-12)
    cv = context[context_valid]
    context_relief = float(np.percentile(cv, 95) - np.percentile(cv, 5))
    return {
        "slope_histogram": hist.tolist(),
        "slope_median_deg": float(np.median(slopes)),
        "slope_p90_deg": float(np.percentile(slopes, 90)),
        "relief_m": float(
            np.percentile(local_values, 95) - np.percentile(local_values, 5)
        ),
        "tpi_std_m": float(np.std(tpi[valid])),
        "residual_rms_m": float(np.sqrt(np.mean(residual**2))),
        "anisotropy": anisotropy,
        "context_relief_m": context_relief,
        "context_std_m": float(np.std(cv)),
        "valid_fraction": float(valid.mean()),
        "context_valid_fraction": float(context_valid.mean()),
        "altitude_m": float(np.median(local_values)),
    }
