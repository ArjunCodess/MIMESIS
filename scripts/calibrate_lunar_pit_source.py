"""Check a documented calibration proxy, without freezing an exact rim or any nomination."""
from pathlib import Path
import argparse
import hashlib
import json
import requests
import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.windows import from_bounds
from src.feature_v10 import Feature, measure_exterior

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/discovery_v10'
META = ROOT / 'data/metadata/discovery_v10'
parser = argparse.ArgumentParser(__doc__)
parser.add_argument('--site', choices=['tranquillitatis','marius'], default='tranquillitatis')
args = parser.parse_args()
site = {'tranquillitatis': {'atlas_id':3,'lat':8.3355,'lon':33.222,'diameter':146,'folder':'moon','product':'TRANQPIT1','quality_folder':'moon_quality'},
        'marius': {'atlas_id':1,'lat':14.0917,'lon':303.2299,'diameter':92,'folder':'moon_marius','product':'MARIUSPIT01','quality_folder':'moon_marius'}}[args.site]
atlas_url = 'https://lroc.im-ldi.com/atlases/pits/' + str(site['atlas_id'])
response = requests.get(atlas_url, timeout=45)
response.raise_for_status()
(META / (args.site+'-atlas.html')).write_text(response.text, encoding='utf-8')
terrain_path = RAW / site['folder'] / ('NAC_DTM_'+site['product']+'.TIF')
quality_path = RAW / site['quality_folder'] / ('NAC_DTM_'+site['product']+'_CONF.IMG')
with rasterio.open(terrain_path) as dtm, rasterio.open(quality_path) as confidence:
    corners = [(0,0),(dtm.width,0),(0,dtm.height),(dtm.width,dtm.height)]
    grid_difference = max(np.linalg.norm(np.asarray(dtm.transform*point)-np.asarray(confidence.transform*point)) for point in corners)
    if dtm.shape != confidence.shape or grid_difference > .0001 or dtm.crs.to_dict() != confidence.crs.to_dict():
        raise ValueError('Terrain and native class grid must coincide')
    cx, cy = Transformer.from_crs(dtm.crs.geodetic_crs, dtm.crs, always_xy=True).transform(site['lon'],site['lat'])
    window = from_bounds(cx-600, cy-600, cx+600, cy+600, dtm.transform).round_offsets().round_lengths()
    z = dtm.read(1, window=window, masked=True)
    classes = confidence.read(1, window=window)
    transform = dtm.window_transform(window)
    rows, columns = np.indices(z.shape)
    x = transform.c + (columns + .5)*transform.a
    y = transform.f + (rows + .5)*transform.e
    results = []
    for edited in [False, True]:
        mask = ~np.ma.getmaskarray(z) & np.isin(classes, [10,11,12,13,14] + ([15] if edited else []))
        radius = np.hypot(x-cx,y-cy)
        annulus = (radius >= site['diameter']/2) & (radius <= 2*site['diameter'])
        for support in [10,20,40]:
            result = measure_exterior(z.data, mask, x, y, Feature(cx,cy,site['diameter']), dtm.res[0], support)
            results.append({'include_manually_edited_class_15': edited, 'unsmoothed_annulus_quality_fraction': float(mask[annulus].mean()), **result})
report = {'state': 'calibration_proxy_source_test_only', 'atlas': atlas_url,
          'atlas_sha256': hashlib.sha256(response.content).hexdigest(),
          'site':args.site, 'documented_center_lat_lon': [site['lat'],site['lon']], 'proxy_diameter_m': site['diameter'],
          'terrain_source':terrain_path.relative_to(ROOT).as_posix(), 'confidence_source':quality_path.relative_to(ROOT).as_posix(),
          'terrain_sha256':hashlib.file_digest(terrain_path.open('rb'),'sha256').hexdigest(),
          'confidence_sha256':hashlib.file_digest(quality_path.open('rb'),'sha256').hexdigest(),
          'terrain_confidence_grid_max_corner_difference_m': float(grid_difference),
          'geometry': 'Circular proxy using the published maximum funnel diameter, not a delineated rim polygon.',
          'source_grid_center_m': [cx,cy], 'measurements': results,
          'limits': ['Calibration source exposed before any nominations; not a validation case.',
                     'A source-mask pass does not establish effective terrain resolution or geological truth.',
                     'No triad, control comparison or novelty outcome is computed.']}
output_name = 'lunar_calibration_proxy.json' if args.site=='tranquillitatis' else 'marius_calibration_proxy.json'
(ROOT / 'artifacts/reports/discovery_v10' / output_name).write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
print([(r['support_m'],r['include_manually_edited_class_15'],r['state'],r.get('valid_fraction')) for r in results])
