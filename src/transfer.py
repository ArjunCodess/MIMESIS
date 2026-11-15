"""Exploratory transfer feasibility, geometry, and explicit evidence gates."""

from itertools import combinations
import math

import numpy as np
from pyproj import CRS, Transformer
from shapely import transform
from shapely.geometry import Polygon, box, mapping, shape

from .validation import paired_sign_test


def square_geometry(longitude, latitude, width_m, radius_m=None):
    """Densified square in its own azimuthal equidistant frame."""
    datum = f"+R={radius_m}" if radius_m else "+datum=WGS84"
    local = CRS.from_proj4(f"+proj=aeqd +lat_0={latitude} +lon_0={longitude} {datum} +units=m")
    inverse = Transformer.from_crs(local, local.geodetic_crs, always_xy=True)
    half = width_m / 2
    points = []
    for a, b in [((-half, -half), (half, -half)), ((half, -half), (half, half)), ((half, half), (-half, half)), ((-half, half), (-half, -half))]:
        points.extend(inverse.transform(a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])) for t in np.linspace(0, 1, 21)[:-1])
    return mapping(Polygon(points))


def contexts_disjoint(a, b):
    """Compare actual Earth polygons in a shared local frame, including dateline."""
    local = CRS.from_proj4(f"+proj=aeqd +lat_0={a['latitude']} +lon_0={a['longitude']} +datum=WGS84 +units=m")
    project = Transformer.from_crs(4326, local, always_xy=True).transform
    left = transform(shape(a['context_geometry']), project, interleaved=False)
    right = transform(shape(b['context_geometry']), project, interleaved=False)
    # Boundary contact is allowed; shared area is not. Numerical tolerance is 1m².
    return left.intersection(right).area <= 1


def exact_pair_diagnostics(candidates, slope_tolerance_deg, relief_tolerance_m, regional_frame=False):
    counts = dict(total_pairs=0, geometry_pass=0, slope_pass=0, relief_pass=0, all_constraints_pass=0)
    feasible = []
    missing_descriptors = []
    for a, b in combinations(candidates, 2):
        counts['total_pairs'] += 1
        geometric = (abs(a['easting_m'] - b['easting_m']) >= 80000 or abs(a['northing_m'] - b['northing_m']) >= 80000) if regional_frame and a['region_id'] == b['region_id'] else contexts_disjoint(a, b)
        counts['geometry_pass'] += int(geometric)
        fa, fb = a.get('features', {}).get('500'), b.get('features', {}).get('500')
        if fa is None or fb is None:
            missing_descriptors.append([a['id'], b['id']])
            continue
        slope = abs(fa['slope_median_deg'] - fb['slope_median_deg']) <= slope_tolerance_deg
        relief = abs(fa['relief_m'] - fb['relief_m']) <= relief_tolerance_m
        counts['slope_pass'] += int(slope)
        counts['relief_pass'] += int(relief)
        if geometric and slope and relief:
            counts['all_constraints_pass'] += 1
            feasible.append([a['id'], b['id']])
    return {**counts, 'feasible_pairs': feasible, 'missing_descriptor_pairs': missing_descriptors, 'state': 'feasible_edges_exist' if feasible else 'no_feasible_pair', 'interpretation': 'Exact enumeration of pair constraints; edge count is not a maximum matching or an independent sample size'}


def allocate_controls(nominations, candidates, slope_tolerance_deg, relief_tolerance_m):
    """Deterministic exploratory assignment with no block reuse or context overlap."""
    lookup = {c['id']: c for c in candidates}
    used, selected, excluded = [], [], []
    reserved = {r['candidate_id'] for r in nominations}
    for row in nominations:
        nominee = lookup[row['candidate_id']]
        if any(not contexts_disjoint(nominee, block) for block in used):
            excluded.append({**row, 'reason': 'nomination overlaps a previously allocated context'})
            continue
        controls = []
        for control in candidates:
            if control['id'] in reserved or control['id'] in {b['id'] for b in used}:
                continue
            pair = exact_pair_diagnostics([nominee, control], slope_tolerance_deg, relief_tolerance_m)
            if pair['all_constraints_pass'] and all(contexts_disjoint(control, block) for block in used):
                fa, fb = nominee['features']['500'], control['features']['500']
                distance = abs(fa['slope_median_deg'] - fb['slope_median_deg']) / slope_tolerance_deg + abs(fa['relief_m'] - fb['relief_m']) / relief_tolerance_m
                controls.append((distance, control['id'], control))
        if not controls:
            excluded.append({**row, 'reason': 'no unused nonoverlapping descriptor-matched control'})
            continue
        control = min(controls, key=lambda x: (x[0], x[1]))[2]
        selected.append({**row, 'control_id': control['id'], 'state': 'exploratory_pair_only'})
        used.extend([nominee, control])
    return {'pairs': selected, 'exclusions': excluded, 'rule': 'Target-ID order, frozen rank nomination, nearest slope/relief match then ID; greedy allocation is not maximum cardinality'}


def reference_gate(reference):
    required = ('source_identifier', 'independent_authorship', 'coverage_verified', 'positional_accuracy_m', 'geological_method', 'tolerance_justification', 'blinding_verified')
    missing = [name for name in required if not reference.get(name)]
    return {'state': 'reference_ready' if not missing else 'missing_reference_abstention', 'missing': missing, 'contact_f1': None}


def inference(differences, independent_units=False, missing_pairs=0, equivalence_margin=None):
    if any(not math.isfinite(v) for v in differences):
        raise ValueError('Differences must be finite; report missing observations separately')
    if not differences or missing_pairs:
        return {'state': 'missing_data_abstention', 'pair_count': len(differences), 'missing_pairs': missing_pairs, 'one_sided_p': None}
    sign = paired_sign_test(differences)
    state = 'supported_superiority' if independent_units and sign['one_sided_p'] is not None and sign['one_sided_p'] < .05 else 'inconclusive'
    return {**sign, 'state': state, 'independence_verified': independent_units, 'equivalence_margin': equivalence_margin, 'equivalence': 'not_established', 'limitation': 'No equivalence inference from non-significance; a margin alone supplies no justified equivalence interval or design. Wilcoxon cannot be inferred from win count.'}


def catalog_local_feasibility(item, radius_m=3396190):
    """Metadata coverage only: actual item polygon, not its rectangular bbox."""
    geometry = shape(item['geometry'])
    center = geometry.representative_point()
    # Unwrap longitude about this point before projecting Mars geometry.
    local = CRS.from_proj4(f'+proj=aeqd +lat_0={center.y} +lon_0={center.x} +R={radius_m} +units=m')
    project = Transformer.from_crs(local.geodetic_crs, local, always_xy=True)
    footprint = transform(geometry, project.transform, interleaved=False)
    fraction = footprint.intersection(box(-10000, -10000, 10000, 10000)).area / 400000000
    return {'longitude': center.x, 'latitude': center.y, 'center_rule': 'Shapely representative point of actual source footprint, fixed without viewing elevations; infeasible here does not exclude a shifted window elsewhere in the product', 'local_geometry': square_geometry(center.x, center.y, 20000, radius_m), 'context_geometry': square_geometry(center.x, center.y, 80000, radius_m), 'local_polygon_coverage_fraction': fraction, 'geometry_feasible': fraction >= .95, 'valid_pixel_fraction': None, 'state': 'metadata_geometry_only', 'limitation': 'Polygon coverage does not establish valid DTM pixels, relief, camera quality, reference availability or independence from MOLA'}
