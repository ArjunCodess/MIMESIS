"""Inspect a registered 3DEP alternative to the unregistered CAVES clouds."""
from pathlib import Path
import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
import numpy as np
import rasterio
from rasterio.windows import from_bounds
from scipy.ndimage import minimum_filter

ROOT = Path(__file__).resolve().parents[1]
metadata = ROOT / 'data/metadata/discovery_v10'
parser = argparse.ArgumentParser(__doc__)
parser.add_argument('--tile-record', type=Path, default=metadata / 'earth-pilot-tile.json')
parser.add_argument('--project-metadata', type=Path)
parser.add_argument('--report', type=Path, default=ROOT / 'artifacts/reports/discovery_v10/registered_earth_source_qa.json')
args = parser.parse_args()
tile_record = json.loads(args.tile_record.read_text())
tile = ROOT / 'data/raw/discovery_v10/earth' / tile_record['downloadURL'].rsplit('/', 1)[-1]
project_xml = args.project_metadata.resolve() if args.project_metadata else None
project = ET.parse(project_xml) if project_xml else None
# The survey notes identify this broad area through UTM zone 12 stations.
# Their unspecified datum is adequate for locating a broad search crop only.
# No scanner-to-world transformation or exact pit rim is inferred.
bounds = [295000, 4812600, 295650, 4813400]
with rasterio.open(tile) as dataset:
    if not dataset.crs or not dataset.crs.is_projected or dataset.res != (1., 1.):
        raise ValueError('Expected the acquired projected one-metre 3DEP tile')
    window = from_bounds(*bounds, transform=dataset.transform).round_offsets().round_lengths()
    values = dataset.read(1, window=window, masked=True)
    valid = ~np.ma.getmaskarray(values) & np.isfinite(values.data)
    support = []
    for sigma in [10, 20, 40]:
        radius = 3 * sigma + 1
        usable = minimum_filter(valid, size=2 * radius + 1, mode='constant', cval=0)
        support.append({'gaussian_sigma_m': sigma, 'square_mask_radius_m': radius, 'usable_cells_within_crop': int(usable.sum())})
    report = {'state': 'registered_source_available_feature_qualification_pending' if valid.any() else 'no_valid_terrain_in_search_crop',
              'source': tile.relative_to(ROOT).as_posix(), 'sha256': hashlib.file_digest(tile.open('rb'), 'sha256').hexdigest(),
              'source_catalogue': tile_record['metaUrl'], 'actual_crs_wkt': dataset.crs.to_wkt(), 'pixel_m': list(dataset.res),
              'search_crop_bounds_native_m': bounds, 'search_crop_shape': list(values.shape), 'valid_fraction': float(valid.mean()),
              'elevation_range_m': [float(values.min()), float(values.max())] if valid.any() else None, 'support': support,
              'project_metadata': {'path': project_xml.relative_to(ROOT).as_posix(), 'sha256': hashlib.file_digest(project_xml.open('rb'), 'sha256').hexdigest(),
                                   'acquisition_begin': project.findtext('.//begdate'), 'acquisition_end': project.findtext('.//enddate'),
                                   'horizontal_datum': project.findtext('.//horizdn'), 'vertical_accuracy_statement': project.findtext('.//vertaccr'),
                                   'processing': project.findtext('.//procdesc')} if project is not None else None,
              'limits': ['Search crop is not a feature polygon, nomination or independent control.',
                         'Tile-specific ground density and interpolation near a pit remain unchecked.',
                         'Project identifier dates must not be treated as acquisition dates.',
                         'Project accuracy target is not a measured pit-specific uncertainty distribution.',
                         'The acquired standard tile is actually 1 m; vendor source products may have a different posting.',
                         'Survey-station UTM datum is unspecified; no CAVES registration has been solved.',
                         'Independent rim mapping, orthophotography and source-footprint correspondence remain required.']}
args.report.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
print(json.dumps({k: report[k] for k in ['state', 'search_crop_shape', 'valid_fraction', 'support']}, indent=2))
