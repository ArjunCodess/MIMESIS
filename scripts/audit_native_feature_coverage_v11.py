"""Audit native raster support without extracting withheld terrain descriptors."""
import json
from pathlib import Path

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.windows import from_bounds

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / 'data/metadata/discovery_v11'


def coverage(path, longitude, latitude, diameter=None, quality_path=None):
    with rasterio.open(ROOT / path) as dataset:
        x, y = Transformer.from_crs(dataset.crs.geodetic_crs, dataset.crs, always_xy=True, force_over=True).transform(longitude, latitude)
        window = from_bounds(x-1000, y-1000, x+1000, y+1000, dataset.transform).round_offsets().round_lengths()
        z = dataset.read(1, window=window, masked=True, boundless=True)
        valid = ~np.ma.getmaskarray(z) & np.isfinite(z.data)
        if quality_path:
            with rasterio.open(ROOT / quality_path) as quality:
                if quality.shape != dataset.shape or not np.allclose(tuple(quality.transform), tuple(dataset.transform), rtol=0, atol=.0001):
                    raise ValueError('Quality grid does not register with native heights')
                valid &= np.isin(quality.read(1, window=window, boundless=True, fill_value=0), [10, 11, 12, 13, 14])
        result = {'native_posting_m': dataset.res[0], 'native_crs': dataset.crs.to_string(),
                  'search_crop_valid_fraction': float(valid.mean()),
                  'quality_basis': 'finite native heights and documented correlation classes' if quality_path else 'finite native heights only; extraction-quality qualification remains unresolved'}
        if diameter:
            t = dataset.window_transform(window)
            row, col = np.indices(valid.shape)
            xx = t.c+(col+.5)*t.a-x
            yy = t.f+(row+.5)*t.e-y
            r = np.hypot(xx, yy)
            region = (r >= diameter/2) & (r <= 2*diameter)
            angles = (np.degrees(np.arctan2(xx, yy))+360) % 360
            fractions = [float(valid[region & (angles >= k*30) & (angles < (k+1)*30)].mean()) for k in range(12)]
            result.update(proxy_diameter_m=diameter, fixed_annulus_valid_fraction=float(valid[region].mean()),
                          sector_valid_fractions=fractions, all_native_sectors_pass=all(value >= .95 for value in fractions))
        return result


def main():
    inventory = json.loads((META / 'lunar-feature-inventory.json').read_text())
    lunar = []
    for identifier, product, terrain_folder, quality_folder in [
        (1, 'MARIUSPIT01', 'moon_marius', 'moon_marius'), (3, 'TRANQPIT1', 'moon', 'moon_quality'),
        (10, 'PRCLRMPIT01', 'moon_prclrmpit01', 'moon_prclrmpit01'), (11, 'PRCLRMPIT01', 'moon_prclrmpit01', 'moon_prclrmpit01'),
        (6, 'INGENIIPIT', 'moon_ingeniipit', 'moon_ingeniipit')]:
        fields = next(row['fields'] for row in inventory if row['atlas_id'] == identifier)
        base = 'NAC_DTM_' + product
        path = 'data/raw/discovery_v10/' + terrain_folder + '/' + base + '.TIF'
        quality = 'data/raw/discovery_v10/' + quality_folder + '/' + base + '_CONF.IMG'
        lunar.append({'atlas_id': identifier, 'name': fields['Name'], 'terrain_path': path,
                      **coverage(path, float(fields['Long.']), float(fields['Lat.']), float(fields['Funnel Max. Diam.']), quality)})
    joined = json.loads((ROOT / 'artifacts/reports/discovery_v11/mars_cave_dtm_intersections.json').read_text())
    intake = json.loads((META / 'mars-feature-source-intake.json').read_text())
    mars = []
    for feature in joined['hits']:
        for product in feature['dtm_products']:
            packet = next(row for row in intake if row['product'] == product)
            asset = next(row for row in packet['assets'] if row['path'].endswith('.IMG'))
            mars.append({'id': feature['id'], 'product': product, 'terrain_path': asset['path'],
                         **coverage(asset['path'], feature['longitude'], feature['latitude'], feature['diameter_m'])})
    destination = ROOT / 'artifacts/reports/discovery_v11/native_feature_coverage.json'
    destination.write_text(json.dumps({'scope': 'Source finite-mask and documented quality preflight, not terrain descriptors or validation outcomes',
                                       'geometry': 'Published diameter circles where known, not exact mapped rims', 'lunar': lunar, 'mars': mars,
                                       'validation_eligible_cases': 0,
                                       'remaining': ['verified rims', 'complete source-quality evidence', 'independent geological controls', 'calibration and protocol freeze']}, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('Audited lunar features:', len(lunar), 'Martian feature/product intersections:', len(mars))
    print('Qualified confirmatory cases: 0; finite coverage is not full qualification')


if __name__ == '__main__':
    main()
