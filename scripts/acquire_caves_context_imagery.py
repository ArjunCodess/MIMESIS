"""Acquire a source-locked NAIP calibration crop around the Indian Tunnel survey area."""
from pathlib import Path
import hashlib
import json
import requests
import rasterio

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / 'data/metadata/discovery_v10'
RAW = ROOT / 'data/raw/discovery_v10/earth'
base = 'https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer'
footprints = json.loads((META / 'indian-tunnel-naip-footprints.json').read_text())['response']['features']
latest = max(row['attributes']['Year'] for row in footprints)
selected = sorted([row['attributes'] for row in footprints if row['attributes']['Year'] == latest], key=lambda row: row['OBJECTID'])
params = {'f': 'json', 'bbox': '295000,4812600,295650,4813400', 'bboxSR': 26912, 'imageSR': 26912,
          'size': '1084,1334', 'format': 'tiff', 'pixelType': 'U8', 'interpolation': 'RSP_NearestNeighbor',
          'bandIds': '0,1,2,3', 'adjustAspectRatio': 'false',
          'mosaicRule': json.dumps({'mosaicMethod': 'esriMosaicLockRaster', 'lockRasterIds': [row['OBJECTID'] for row in selected]})}
response = requests.get(base + '/exportImage', params=params, timeout=90)
response.raise_for_status()
export = response.json()
if 'error' in export or 'href' not in export:
    raise ValueError(f'NAIP export rejected: {export}')
download = requests.get(export['href'], timeout=90)
download.raise_for_status()
path = RAW / 'IndianTunnel_NAIP2021_service_crop.tif'
path.write_bytes(download.content)
with rasterio.open(path) as raster:
    if raster.count != 4 or raster.width != 1084 or raster.height != 1334:
        raise ValueError('Unexpected NAIP export dimensions or bands')
    qa = {'crs_wkt': raster.crs.to_wkt(), 'bounds': list(raster.bounds), 'pixel_spacing_m': list(raster.res),
          'bands': raster.count, 'valid_mask_fraction': float((raster.dataset_mask() > 0).mean())}
record = {'source_service': base, 'request': params, 'export_response': export, 'source_frames': selected,
          'path': path.relative_to(ROOT).as_posix(), 'sha256': hashlib.file_digest(path.open('rb'), 'sha256').hexdigest(),
          'qa': qa, 'exposure': 'calibration source; inspected before any nominations or validation freeze',
          'limits': ['Service-generated resampled crop, not a native original frame.',
                     'Image validity does not distinguish shadows, vegetation or anthropogenic surfaces.',
                     'Two neighbouring frames from one acquisition do not constitute independent validation cases.',
                     'No rim has yet been delineated or independently validated.']}
(META / 'indian-tunnel-naip-source.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(qa, indent=2))
