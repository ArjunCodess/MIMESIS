"""Reserved HLS context, kept outside the terrain scoring contract."""

from pathlib import Path
import json
import numpy as np
from PIL import Image
from pyproj import Transformer
from scipy.ndimage import map_coordinates
import tifffile


def hls_context(directory: Path, inverse, output: Path, extent_m: int = 116000):
    metadata = json.loads(next(directory.glob("*stac.json")).read_text())
    properties = metadata["properties"]
    if properties["proj:epsg"] not in range(32601, 32800) or properties[
        "proj:shape"
    ] != [3660, 3660]:
        raise ValueError(
            "HLS scene must declare a WGS84 UTM CRS and a 3660 square raster"
        )
    transform = properties["proj:transform"]
    if transform[0] != 30 or transform[4] != -30 or transform[1] or transform[3]:
        raise ValueError("HLS transform must be a north-up 30 m grid")
    # Project cell centers into the exact source CRS. Negative UTM northings are
    # part of this source's EPSG:32619 encoding; never silently switch hemispheres.
    axis = np.arange(-extent_m / 2 + 62.5, extent_m / 2, 125)
    x, y = np.meshgrid(axis, -axis)
    lon, lat = inverse.transform(x, y)
    utm_x, utm_y = Transformer.from_crs(
        4326, properties["proj:epsg"], always_xy=True
    ).transform(lon, lat)
    col, row = (utm_x - transform[2]) / 30 - 0.5, (utm_y - transform[5]) / -30 - 0.5
    fmask = tifffile.imread(next(directory.glob("*Fmask.tiff")))
    if fmask.shape != (3660, 3660):
        raise ValueError("HLS mask shape differs from STAC")
    # HLS Fmask bits 0..5: cirrus, cloud, adjacent, shadow, snow/ice, water.
    source_clear = (fmask != 255) & ((fmask & 63) == 0)
    good = (
        map_coordinates(
            source_clear.astype(float), [row, col], order=1, mode="constant", cval=0
        )
        > 0.999
    )
    channels = []
    for band in ("B04", "B03", "B02"):
        values = tifffile.imread(next(directory.glob(f"*{band}.tiff")))
        sampled = map_coordinates(
            values.astype(float), [row, col], order=1, mode="constant", cval=-9999
        )
        # Every bilinear contributor must be valid; a mixed fill/reflectance
        # value must not become a usable optical pixel at a source boundary.
        good &= (
            map_coordinates(
                (values != -9999).astype(float),
                [row, col],
                order=1,
                mode="constant",
                cval=0,
            )
            > 0.999
        )
        channels.append(sampled * 0.0001)
    rgb = np.stack(channels, axis=-1)
    # Fixed display stretch only. Colors never enter a cross-body loss.
    rgb = (np.clip(rgb / 0.4, 0, 1) ** (1 / 2.2) * 255).astype("uint8")
    rgb[~good] = [230, 226, 214]
    Image.fromarray(rgb).save(output)
    return good, {
        "scene_id": metadata["id"],
        "acquired_at": properties["datetime"],
        "mask_rule": "Exclude fill and HLS Fmask bits 0 through 5",
        "display": "RGB B04/B03/B02; reflectance/0.4, gamma 1/2.2",
        "image": output.name,
        "interpreted": False,
        "role": "reserved_context",
        "valid_projected_grid_fraction": float(good.mean()),
    }
