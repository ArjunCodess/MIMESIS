"""Replay a published terrain-ranking result from pinned upstream feature records.

Upstream code executes only from ignored local snapshots. The receipt credits
its authors and distinguishes ranking replay from raw DEM reconstruction.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def main():
    records = json.loads((ROOT / 'artifacts/reports/submission-audit-2026-11-15/repositories.json').read_text())
    record = next(row for row in records if row['repo'] == 'shishir-kuet/terrestrial-analog-finder')
    source = ROOT / 'data/raw/comparison_sources' / record['repo'] / record['head']
    sys.path.insert(0, str(source / 'backend'))
    from app.registry import FEATURES
    from app.similarity import rank
    from app.store import Store
    spec = importlib.util.spec_from_file_location('upstream_sensitivity', source / 'backend/pipeline/sensitivity.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    store = Store(source / 'data')
    targets = [row for row in store.targets if row['status'] == 'ok']
    pool, scales = store.reference_pool, store.scales
    published_path = source / 'data/processed/sensitivity.json'
    published = json.loads(published_path.read_text())
    # Preserve the recorded feature order: consuming RNG draws for a later,
    # zero-weight feature changes the next draw even though it adds no score.
    weights = published['baseline']['weights']
    baseline = {target['id']: module.order(target, pool, weights, scales) for target in targets}
    rng = np.random.default_rng(2026)
    draws = []
    for _ in range(20):
        changed = {key: value * float(rng.uniform(.5, 1.5)) for key, value in weights.items()}
        draws.append(module.compare(baseline, {target['id']: module.order(target, pool, changed, scales) for target in targets}))
    experiments = [{'name': published['experiments'][0]['name'], **{key: float(np.median([draw[key] for draw in draws])) for key in draws[0] if key != 'targets_without_valid_window'}}]
    for key in weights:
        changed = {name: value for name, value in weights.items() if name != key}
        experiments.append({'name': f'Drop feature: {FEATURES[key].label}', **module.compare(baseline, {target['id']: module.order(target, pool, changed, scales) for target in targets})})
    checks = []
    for actual in experiments:
        expected = next(row for row in published['experiments'] if row['name'] == actual['name'])
        comparisons = {key: abs(actual[key] - expected[key]) for key in actual if key not in ['targets_without_valid_window', 'name']}
        checks.append({'experiment': expected['name'], 'replayed': actual,
                       'maximum_absolute_difference': max(comparisons.values()),
                       'matches_within_1e_10': max(comparisons.values()) <= 1e-10})
    tops = []
    for target in targets:
        ranking, excluded, _ = rank(target, store.earth, weights, scales)
        tops.append({'target_id': target['id'], 'ranked': len(ranking), 'excluded': len(excluded),
                     'top_candidate_id': ranking[0].location['id'], 'similarity_index': ranking[0].similarity_index})
    result = {
        'attribution': 'Terrestrial Analog Finder, shishir-kuet; original implementation and published processed feature records',
        'repository': 'https://github.com/' + record['repo'], 'commit': record['head'],
        'scope': 'Replay of scores and feature/weight sensitivity from upstream processed records, not independent reconstruction of raw DEMs',
        'source_sha256': hashlib.file_digest((source / 'data/processed/locations.json').open('rb'), 'sha256').hexdigest(),
        'reference_receipt_sha256': hashlib.file_digest(published_path.open('rb'), 'sha256').hexdigest(),
        'targets': len(targets), 'reference_earth_pool': len(pool), 'checks': checks, 'rankings': tops,
        'all_replayed_experiments_match': all(row['matches_within_1e_10'] for row in checks),
        'not_reproduced': ['raw elevation acquisition and feature extraction', 'coarser-grid and smaller-window experiments requiring upstream raw caches',
                           'field or geological validation', 'any claimed scientific novelty'],
    }
    destination = ROOT / 'artifacts/reports/replication_v11'
    destination.mkdir(exist_ok=True)
    (destination / 'terrain_finder_replay.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in ['targets', 'reference_earth_pool', 'all_replayed_experiments_match']}, indent=2))
    print('Replayed sensitivity experiments:', len(checks))


if __name__ == '__main__':
    main()
