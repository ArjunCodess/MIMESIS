"""Measure location changes across scoring contracts and derivative supports.

Uses frozen regional descriptors, not a new global search or raw-DEM validation.
Run from the repository root: python scripts/measure_site_stability.py
"""
import hashlib
import json
from pathlib import Path
import shutil

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np

from src.scalar_baseline import fit_scales, rank_baseline
from src.site_stability import center_distance_km, geographic_matches, window_iou

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / 'apps/web/public/research'
PAPER = ROOT / 'artifacts/paper'
REPORT = ROOT / 'artifacts/reports/site_stability.json'
SOURCE = PUBLIC / 'bundle.json'
KEYS = ['relief_m', 'slope_median_deg', 'slope_p90_deg', 'residual_rms_m']


def main():
    bundle = json.loads(SOURCE.read_text(encoding='utf-8'))
    candidates = bundle['candidates']
    by_id = {row['id']: row for row in candidates}
    values = {s: [[c['features'][s][key] for key in KEYS] for c in candidates] for s in ['500', '1000']}
    scales = fit_scales(values['500'])
    cases = []
    features = []
    for target in bundle['targets']:
        methods = []
        for method in ['scalar', 'multigroup']:
            orders = []
            for support, field in [('500', 'rankings'), ('1000', 'rankings_1000')]:
                if method == 'scalar':
                    losses = rank_baseline(values[support], [target['features'][support][key] for key in KEYS], scales)
                    order = sorted(np.flatnonzero(np.isfinite(losses)), key=lambda i: (losses[i], candidates[i]['id']))
                    orders.append([candidates[i]['id'] for i in order])
                else:
                    orders.append([r['id'] for r in bundle[field][target['id']]['candidates']])
            top_sets = [[by_id[item] for item in order[:10]] for order in orders]
            winners = [items[0] for items in top_sets]
            ranks = [{item: i + 1 for i, item in enumerate(order)} for order in orders]
            common = set(ranks[0]) & set(ranks[1])
            compromise_id = min(common, key=lambda item: (max(r[item] for r in ranks), sum(r[item] for r in ranks), item))
            compromise = by_id[compromise_id]
            choice = {key: compromise[key] for key in ['id', 'name', 'region', 'latitude', 'longitude', 'source_ids', 'image', 'footprint']}
            choice['ranks'] = [r[compromise_id] for r in ranks]
            choice['features'] = {s: {key: compromise['features'][s][key] for key in KEYS} for s in values}
            summary = {'method': method, 'top_ten_exact_overlap': len(set(orders[0][:10]) & set(orders[1][:10])),
                       'winner_distance_km': center_distance_km(*winners), 'winner_footprint_iou': window_iou(*winners),
                       'geographic_matches': geographic_matches(*top_sets, [5, 10, 20, 40]),
                       'winners': [{key: w[key] for key in ['id', 'region', 'latitude', 'longitude', 'easting_m', 'northing_m', 'footprint']} for w in winners],
                       'minimax_rank_choice': choice}
            methods.append(summary)
            features.append({'type': 'Feature', 'geometry': {'type': 'Polygon', 'coordinates': [choice['footprint']]},
                             'properties': {'target_id': target['id'], 'target_name': target['name'], 'method': method,
                                            'candidate_id': choice['id'], 'region': choice['region'], 'ranks': choice['ranks'],
                                            'status': 'exploratory_terrain_shortlist', 'source_ids': choice['source_ids'],
                                            'field_ready': False, 'geological_validation': False}})
        method_distances = [center_distance_km(methods[0]['winners'][i], methods[1]['winners'][i]) for i in range(2)]
        cases.append({'target_id': target['id'], 'target_name': target['name'], 'body': target['body'],
                      'methods': methods, 'between_method_distance_km': method_distances,
                      'between_method_region_changes': [methods[0]['winners'][i]['region'] != methods[1]['winners'][i]['region'] for i in range(2)]})
    within = [m['winner_distance_km'] for c in cases for m in c['methods']]
    between = [d for c in cases for d in c['between_method_distance_km']]
    result = {'schema_version': '1.0', 'study': 'Regional location stability across two scoring contracts and two supports',
              'source_bundle_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
              'implementation_sha256': {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
                                        for p in [Path(__file__).resolve(), ROOT / 'src/site_stability.py', ROOT / 'src/scalar_baseline.py']},
              'candidate_count': len(candidates), 'regions': sorted({c['region'] for c in candidates}),
              'window_width_m': 20000, 'candidate_stride_m': 3000, 'supports_m': [500, 1000],
              'method_contracts': {'scalar': 'Four transformed scalar observables, fixed 500 m pool IQR scaling, equal-weight RMS discrepancy; src/scalar_baseline.py retains method provenance.',
                                   'multigroup': 'Frozen MIMESIS maximum loss over 35 weight, support and erosion scenarios; four groups with weights 0.40/0.25/0.15/0.20. This contract already includes cross-support robustness.'},
              'design': 'Post hoc descriptive follow-up on previously inspected regional records. Supports and methods are not independent replicates. No inferential p-values.',
              'geographic_contract': 'WGS84 geodesic center distances. Square footprint IoU in the shared regional AEQD measurement projection. Maximum cardinality one-to-one top-ten matching at 5/10/20/40 km, with total distance as tie-breaker. Radii are exploratory, not field-operation tolerances.',
              'selection_contract': 'For each target and method, minimize the worse of the two full-pool ranks; break ties by rank sum then candidate ID. This is a terrain shortlist, not qualification.',
              'summary': {'within_method_max_km': max(within), 'within_method_median_km': float(np.median(within)),
                          'between_method_max_km': max(between), 'between_method_median_km': float(np.median(between)),
                          'targets_with_between_method_region_change': sum(any(c['between_method_region_changes']) for c in cases)},
              'cases': cases,
              'limitations': ['Only the Namib and Atacama source pools are searched; no global or previously unrecognized geological-site claim.',
                              '20 km windows at 3 km stride overlap strongly; 3,693 windows are not 3,693 independent sites.',
                              'Scoring contracts differ in observables, weighting and sensitivity aggregation, so the comparison cannot identify a single causal ingredient.',
                              'The multigroup score already includes alternate support; small support shifts there are partly by design.',
                              'Eligibility, geology, access, environmental comparability and field utility remain unverified for every shortlist.',
                              'Earth gravity, atmosphere, radiation and polar illumination are not reproduced by a terrain match.'],
              'claim': 'Original project-level geographic sensitivity result; literature priority and a new geological analogue are not established.'}
    REPORT.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    shutil.copy2(REPORT, PUBLIC / REPORT.name)
    (PUBLIC / 'site-shortlist.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': features}, indent=2) + '\n', encoding='utf-8')
    (ROOT / 'apps/web/src/generated/site-stability.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False,
                         'figure.facecolor': '#f9f7f0', 'axes.facecolor': '#f9f7f0'})
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.3), layout='constrained')
    labels = [c['target_name'] for c in cases]
    for i, case in enumerate(cases):
        scalar = case['methods'][0]
        axes[0].barh(i - .17, scalar['top_ten_exact_overlap'], height=.3, color='#a45334')
        axes[0].barh(i + .17, next(r['matched_pairs'] for r in scalar['geographic_matches'] if r['radius_km'] == 10), height=.3, color='#536c55')
        axes[1].scatter([m['winner_distance_km'] for m in case['methods']], [i - .12, i + .12], color=['#a45334', '#536c55'], s=35)
        axes[1].scatter(case['between_method_distance_km'], [i, i], color='#293b4b', marker='x', s=45)
    axes[0].set(yticks=range(len(cases)), yticklabels=labels, xlim=(0, 10.6), xticks=range(0, 11, 2), xlabel='Top-ten pairs: exact IDs / within 10 km')
    axes[1].set(yticks=range(len(cases)), yticklabels=labels, xscale='symlog', xlim=(-.1, 20000), xlabel='Winning-center displacement, km (symlog)')
    axes[0].plot([], [], color='#a45334', lw=6, label='Exact IDs'); axes[0].plot([], [], color='#536c55', lw=6, label='10 km matching')
    axes[1].scatter([], [], color='#a45334', label='Scalar, scale change'); axes[1].scatter([], [], color='#536c55', label='Multigroup, scale change')
    axes[1].scatter([], [], color='#293b4b', marker='x', label='Scoring contract change')
    for ax in axes:
        ax.invert_yaxis(); ax.legend(frameon=False, fontsize=8, loc='lower center', bbox_to_anchor=(.5, 1.01)); ax.grid(axis='x', alpha=.15)
    fig.savefig(PAPER / 'site-stability.png', dpi=200)
    plt.close(fig)
    shutil.copy2(PAPER / 'site-stability.png', PUBLIC / 'site-stability.png')
    nili = next(c for c in cases if c['target_id'] == 'nili')['methods'][0]
    fig, ax = plt.subplots(figsize=(7, 4.2), layout='constrained')
    origin = nili['winners'][0]
    for winner, color, label in zip(nili['winners'], ['#a45334', '#536c55'], ['500 m support', '1,000 m support']):
        x = (winner['easting_m'] - origin['easting_m']) / 1000
        y = (winner['northing_m'] - origin['northing_m']) / 1000
        ax.add_patch(Rectangle((x - 10, y - 10), 20, 20, facecolor=color, edgecolor=color, alpha=.25, linewidth=2, label=label))
        ax.scatter(x, y, color=color, zorder=3)
    ax.set(xlim=(-14, 14), ylim=(-14, 17), aspect='equal', xlabel='Regional easting offset, km', ylabel='Regional northing offset, km')
    ax.legend(frameon=False, loc='upper left', bbox_to_anchor=(1.02, 1))
    ax.grid(alpha=.15)
    fig.savefig(PAPER / 'nili-window-overlap.png', dpi=200)
    plt.close(fig)
    shutil.copy2(PAPER / 'nili-window-overlap.png', PUBLIC / 'nili-window-overlap.png')
    print(json.dumps(result['summary'], indent=2))
    for case in cases:
        print(case['target_id'], 'method distances km', [round(d, 2) for d in case['between_method_distance_km']])


if __name__ == '__main__':
    main()
