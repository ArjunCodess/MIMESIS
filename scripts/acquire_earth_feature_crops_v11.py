"""Read small native-grid 3DEP windows, retaining their parent product identity."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.windows import from_bounds

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / 'data/metadata/discovery_v11'
OUT = ROOT / 'data/raw/discovery_v11/earth'
OUT.mkdir(parents=True, exist_ok=True)


def acquire(case):
    trials = []
    for source in sorted(case['terrain_products'], key=lambda p: (p['publicationDate'] or '', p['title']), reverse=True):
        url = source['downloadURL']
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif'):
            with rasterio.open('/vsicurl/' + url) as dataset:
                x, y = Transformer.from_crs(4326, dataset.crs, always_xy=True).transform(case['longitude'], case['latitude'])
                window = from_bounds(x-1000, y-1000, x+1000, y+1000, dataset.transform).round_offsets().round_lengths()
                values = dataset.read(1, window=window, masked=True, boundless=True)
                finite = ~np.ma.getmaskarray(values) & np.isfinite(values.data)
                fraction = float(finite.mean())
                trial = {'source': source, 'native_valid_fraction': fraction}
                trials.append(trial)
                if fraction < .95:
                    continue
                target = OUT / (case['id'] + '-3DEP-native-crop.tif')
                profile = dataset.profile.copy()
                profile.update(driver='GTiff', width=values.shape[1], height=values.shape[0], count=1,
                               transform=dataset.window_transform(window), compress='deflate')
                with rasterio.open(target, 'w', **profile) as destination:
                    destination.write(values.filled(dataset.nodata), 1)
                return {'id': case['id'], 'name': case['name'], 'region': case['region'],
                        'latitude': case['latitude'], 'longitude': case['longitude'],
                        'source': source, 'path': target.relative_to(ROOT).as_posix(),
                        'sha256': hashlib.file_digest(target.open('rb'), 'sha256').hexdigest(),
                        'native_crs': dataset.crs.to_string(), 'pixel_m': dataset.res[0],
                        'shape': list(values.shape), 'native_valid_fraction': fraction,
                        'source_trials': trials, 'state': 'native_crop_acquired; not a qualified pit case',
                        'exposure': 'Native heights read for lossless crop and finite-mask QA only; no fine descriptors or ranks computed',
                        'remaining': ['mapped rim and feature identity', 'process evidence', 'local ground density and interpolation',
                                      'vegetation and disturbance masks', 'source accuracy and epoch', 'independent corroboration']}
    return {'id': case['id'], 'name': case['name'], 'region': case['region'],
            'state': 'no_source_crop_passes_finite_coverage', 'source_trials': trials}


if __name__ == '__main__':
    cases = json.loads((META / 'earth-feature-tile-inventory.json').read_text())['cases']
    results = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for result in pool.map(acquire, cases):
            results.append(result)
            print(result['name'], result['state'], flush=True)
            (META / 'earth-feature-crop-intake.json').write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
