"""Apply an attributed scalar baseline to MIMESIS's existing terrain records."""
import hashlib
import json
from pathlib import Path

import numpy as np
from src.scalar_baseline import fit_scales, rank_baseline

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'apps/web/public/research/bundle.json'


def main():
    bundle = json.loads(SOURCE.read_text(encoding='utf-8'))
    candidates = bundle['candidates']
    keys = ['relief_m', 'slope_median_deg', 'slope_p90_deg', 'residual_rms_m']
    values = lambda support: [[row['features'][support][key] for key in keys] for row in candidates]
    scales = fit_scales(values('500'))
    cases = []
    for target in bundle['targets']:
        supports = []
        orders = []
        for support in ['500', '1000']:
            losses = rank_baseline(values(support), [target['features'][support][key] for key in keys], scales)
            order = sorted(np.flatnonzero(np.isfinite(losses)), key=lambda index: (losses[index], candidates[index]['id']))
            orders.append([candidates[index]['id'] for index in order])
            supports.append({'support_m': int(support), 'ranked': len(order),
                             'top_ten': [{'id': candidates[index]['id'], 'name': candidates[index]['name'],
                                          'latitude': candidates[index]['latitude'], 'longitude': candidates[index]['longitude'],
                                          'distance': float(losses[index])} for index in order[:10]]})
        cases.append({'target_id': target['id'], 'target_name': target['name'], 'body': target['body'],
                      'supports': supports, 'top_candidate_changes': orders[0][0] != orders[1][0],
                      'top_ten_overlap': len(set(orders[0][:10]) & set(orders[1][:10]))})
    result = {'source_bundle_sha256': hashlib.file_digest(SOURCE.open('rb'), 'sha256').hexdigest(),
              'method_reference': 'https://github.com/shishir-kuet/terrestrial-analog-finder',
              'implementation': 'Independent four-scalar adaptation; log10(value+1) relief/roughness, identity slopes, fixed 500 m reference-pool IQR scales with standard-deviation fallback, equal-weight RMS distance',
              'features': keys, 'scales': scales.tolist(), 'reference_candidates': len(candidates), 'cases': cases,
              'interpretation': 'Exploratory sensitivity on previously inspected terrain records; existing source eligibility limits remain. Not a new feature-scale triad or independent validation.',
              'claim': 'Rank changes quantify sensitivity to the declared derivative support in this scalar baseline; no geological novelty established'}
    output = ROOT / 'artifacts/reports/replication_v11/scalar_baseline_transfer.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'targets': len(cases), 'reference_candidates': len(candidates),
                      'top_candidate_changes': sum(row['top_candidate_changes'] for row in cases),
                      'top_ten_overlaps': [row['top_ten_overlap'] for row in cases]}, indent=2))


if __name__ == '__main__':
    main()
