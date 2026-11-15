"""Audit local XY sampling; a 3D scanner cloud is not assumed to be a bare-earth DEM."""
from pathlib import Path
import argparse
import json
import numpy as np
from scipy.ndimage import minimum_filter

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'artifacts/reports/discovery_v10'
parser = argparse.ArgumentParser(__doc__)
parser.add_argument('--source', type=Path, default=ROOT / 'data/raw/discovery_v10/caves/IndianTunnel_surface')
parser.add_argument('--report', type=Path, default=REPORTS / 'caves_surface_support.json')
args = parser.parse_args()
source = args.source.resolve()
if not source.is_dir() or not list(source.rglob('*.f32')):
    raise ValueError('Source directory must contain extracted f32 clouds')
results = []
for path in sorted(source.rglob('*.f32')):
    points = np.memmap(path, dtype='<f4', mode='r').reshape(-1, 7)
    lower = np.full(2, np.inf)
    upper = np.full(2, -np.inf)
    for start in range(0, len(points), 1_000_000):
        xy = points[start:start + 1_000_000, :2]
        finite = xy[np.isfinite(xy).all(axis=1)]
        lower = np.minimum(lower, finite.min(axis=0))
        upper = np.maximum(upper, finite.max(axis=0))
    origin = np.floor(lower)
    width, height = (np.floor(upper - origin).astype(int) + 1)
    count = np.zeros((height, width), dtype=np.int64)
    zmin = np.full((height, width), np.inf)
    zmax = np.full((height, width), -np.inf)
    for start in range(0, len(points), 1_000_000):
        xyz = points[start:start + 1_000_000, :3]
        xyz = xyz[np.isfinite(xyz).all(axis=1)]
        ij = np.floor(xyz[:, :2] - origin).astype(int)
        key = (ij[:, 1], ij[:, 0])
        np.add.at(count, key, 1)
        np.minimum.at(zmin, key, xyz[:, 2])
        np.maximum.at(zmax, key, xyz[:, 2])
    occupied = count > 0
    spread = (zmax - zmin)[occupied]
    supports = []
    for support in [10, 20, 40]:
        radius = 3 * support + 1
        valid = minimum_filter(occupied, size=2 * radius + 1, mode='constant', cval=0)
        supports.append({'gaussian_sigma_m': support, 'square_mask_radius_at_1m': radius, 'surviving_cells': int(valid.sum())})
    results.append({'path': path.relative_to(ROOT).as_posix(), 'point_count': len(points), 'grid_cell_m': 1,
                    'xy_bounds_m': [lower.tolist(), upper.tolist()], 'shape_rows_columns': [int(height), int(width)],
                    'occupied_cells': int(occupied.sum()), 'bounding_rectangle_cells': int(count.size),
                    'occupied_fraction_of_rectangle': float(occupied.mean()),
                    'within_cell_vertical_range_m_percentiles_50_90_99': np.percentile(spread, [50, 90, 99]).tolist(),
                    'support_erosion': supports,
                    'interpretation': 'Unclassified XY sampling only. Roof, floor, walls and vegetation can share a cell. Erosion survivors are an optimistic necessary check, not valid exterior terrain or independent features.'})
    print(path.name, supports, flush=True)
args.report.write_text(json.dumps({'state': 'calibration_source_sampling_diagnostic', 'sources': results, 'feature_selection': 'none; no pit outlines inferred', 'mask_contract': 'Same 3-sigma-plus-derivative erosion as feature_v10, applied to observed XY occupancy only; no interpolation or ground classification'}, indent=2) + '\n')
