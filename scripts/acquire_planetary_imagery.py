"""Cache source tiles and reproject independent camera imagery for inspection."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import hashlib
import json
import xml.etree.ElementTree as ET
import numpy as np
from PIL import Image
from pyproj import CRS, Transformer
import requests
from scipy.ndimage import map_coordinates

ROOT = Path(__file__).resolve().parents[1]
NS = {"w": "http://www.opengis.net/wmts/1.0", "o": "http://www.opengis.net/ows/1.1"}


def acquire(target):
    body = target["body"]
    if abs(target["latitude"]) > 80:
        # The equirectangular WAC service is not treated as a validated polar source.
        return {
            "target_id": target["id"],
            "status": "unavailable",
            "reason": "No polar camera mosaic acquired; equirectangular tiles are not silently used as a polar validation layer",
        }
    layer = (
        "CTX_beta01_uncontrolled_5m_Caltech"
        if body == "Mars"
        else "LRO_WAC_Mosaic_Global_303ppd"
    )
    zoom = "8" if body == "Mars" else "7"
    radius = 3396000 if body == "Mars" else 1737400
    label = ROOT / "data/metadata" / f"{layer}.xml"
    capabilities_url = (
        f"https://trek.nasa.gov/tiles/{body}/EQ/{layer}/1.0.0/WMTSCapabilities.xml"
    )
    if not label.exists():
        response = requests.get(capabilities_url, timeout=40)
        response.raise_for_status()
        label.parent.mkdir(parents=True, exist_ok=True)
        label.write_bytes(response.content)
    tree = ET.parse(label)
    matrix = next(
        m
        for m in tree.findall(".//w:TileMatrix", NS)
        if m.findtext("o:Identifier", namespaces=NS) == zoom
    )
    width = int(float(matrix.findtext("w:MatrixWidth", namespaces=NS)))
    height = int(float(matrix.findtext("w:MatrixHeight", namespaces=NS)))
    tile_size = int(matrix.findtext("w:TileWidth", namespaces=NS))
    template = tree.find(".//w:ResourceURL", NS).get("template")
    template = (
        template.replace(
            "{Style}", tree.findtext(".//w:Style/o:Identifier", namespaces=NS)
        )
        .replace(
            "{TileMatrixSet}",
            tree.findtext(".//w:TileMatrixSet/o:Identifier", namespaces=NS),
        )
        .replace("{TileMatrix}", zoom)
    )
    if matrix.findtext("w:TopLeftCorner", namespaces=NS) != "-180.0 90.0":
        raise ValueError("Unsupported WMTS registration")
    lat, lon = target["latitude"], target["longitude"]
    crs = CRS.from_proj4(f"+proj=aeqd +lat_0={lat} +lon_0={lon} +R={radius} +units=m")
    inverse = Transformer.from_crs(
        crs, CRS.from_proj4(f"+proj=longlat +R={radius}"), always_xy=True
    )
    axis = np.arange(-40000 + 50, 40000, 100)
    x, y = np.meshgrid(axis, -axis)
    longitude, latitude = inverse.transform(x, y)
    px = (longitude + 180) / 360 * width * tile_size - 0.5
    py = (90 - latitude) / 180 * height * tile_size - 0.5
    col0, col1 = (
        int(np.floor(px.min() / tile_size)),
        int(np.floor(px.max() / tile_size)),
    )
    row0, row1 = (
        int(np.floor(py.min() / tile_size)),
        int(np.floor(py.max() / tile_size)),
    )
    folder = ROOT / "data/raw" / body.lower() / "imagery" / layer / zoom
    folder.mkdir(exist_ok=True, parents=True)
    records = []
    mosaic = np.zeros(
        ((row1 - row0 + 1) * tile_size, (col1 - col0 + 1) * tile_size, 4),
        dtype=np.uint8,
    )

    def tile(job):
        row, col = job
        url = template.replace("{TileRow}", str(row)).replace("{TileCol}", str(col))
        path = folder / f"{row}-{col}.tile"
        if not path.exists():
            for attempt in range(3):
                response = requests.get(url, timeout=50)
                response.raise_for_status()
                try:
                    image = Image.open(BytesIO(response.content)).convert("RGBA")
                except OSError:
                    if attempt < 2:
                        continue
                    rejected = folder / f"{row}-{col}.rejected"
                    rejected.write_bytes(response.content)
                    return (
                        row,
                        col,
                        np.zeros((tile_size, tile_size, 4), dtype=np.uint8),
                        {
                            "url": url,
                            "status": "corrupt_source_tile",
                            "path": rejected.relative_to(ROOT).as_posix(),
                            "sha256": hashlib.sha256(response.content).hexdigest(),
                        },
                    )
                if image.size != (tile_size, tile_size):
                    raise ValueError("WMTS tile size differs from capabilities")
                path.write_bytes(response.content)
                break
        else:
            image = Image.open(path).convert("RGBA")
        values = np.asarray(image)
        record = {
            "url": url,
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        return row, col, values, record

    jobs = [
        (row, col) for row in range(row0, row1 + 1) for col in range(col0, col1 + 1)
    ]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for row, col, values, record in pool.map(tile, jobs):
            mosaic[
                (row - row0) * tile_size : (row - row0 + 1) * tile_size,
                (col - col0) * tile_size : (col - col0 + 1) * tile_size,
            ] = values
            records.append(record)
    coordinates = [py - row0 * tile_size, px - col0 * tile_size]
    projected = np.stack(
        [
            map_coordinates(
                mosaic[..., channel].astype(float),
                coordinates,
                order=1,
                mode="constant",
                cval=0,
            )
            for channel in range(4)
        ],
        axis=-1,
    ).astype(np.uint8)
    image_name = f"{target['id']}-camera.png"
    Image.fromarray(projected).save(ROOT / "apps/web/public/research" / image_name)
    record = {
        "target_id": target["id"],
        "status": "acquired",
        "source_id": layer,
        "body": body,
        "capabilities_url": capabilities_url,
        "capabilities_sha256": hashlib.sha256(label.read_bytes()).hexdigest(),
        "tiles": records,
        "image": image_name,
        "extent_m": 80000,
        "output_spacing_m": 100,
        "source_equatorial_spacing_m": 2 * np.pi * radius / (width * tile_size),
        "valid_alpha_fraction": float(np.mean(projected[..., 3] > 250)),
        "projection": f"AEQD {lat}, {lon}; R={radius} m",
        "acquired_at": datetime.now(timezone.utc).isoformat(),
        "sensor": "MRO CTX camera" if body == "Mars" else "LRO LROC WAC camera",
        "independence": "Separate optical acquisition from MOLA altimetry; beta mosaic is uncontrolled; absolute co-registration accuracy is not validated"
        if body == "Mars"
        else "Separate WAC optical acquisition; non-polar mosaic orthorectification uses WAC-derived GLD100; not a LOLA hillshade",
        "interpretation_status": "not_assessed",
        "rights": "NASA/JPL/Caltech Murray Lab/MSSS"
        if body == "Mars"
        else "NASA/GSFC/Arizona State University LROC",
    }
    print(
        f"{target['id']}: {len(records)} camera tiles; projected valid alpha {record['valid_alpha_fraction']:.3f}",
        flush=True,
    )
    return record


if __name__ == "__main__":
    protocol = json.loads((ROOT / "configs/protocol.json").read_text())
    records = [acquire(target) for target in protocol["targets"]]
    output = ROOT / "artifacts/reports/planetary_imagery.json"
    output.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    (ROOT / "apps/web/public/research/planetary_imagery.json").write_text(
        output.read_text(), encoding="utf-8"
    )
