"""Publish attributed replication and support-sensitivity records, not a discovery."""
import hashlib
import json
from pathlib import Path
import shutil

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'artifacts/reports/replication_v11'
PUBLIC = ROOT / 'apps/web/public/research'
PAPER = ROOT / 'artifacts/paper'


def main():
    replay_path = REPORT / 'terrain_finder_replay.json'
    transfer_path = REPORT / 'scalar_baseline_transfer.json'
    replay = json.loads(replay_path.read_text())
    transfer = json.loads(transfer_path.read_text())
    if not replay['all_replayed_experiments_match']:
        raise ValueError('A failed replication cannot publish a successful-replay statement')
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11, 'axes.spines.top': False,
                         'axes.spines.right': False, 'figure.facecolor': '#f9f7f0', 'axes.facecolor': '#f9f7f0'})
    fig, ax = plt.subplots(figsize=(8.4, 4.1), layout='constrained')
    labels = [row['target_name'] for row in transfer['cases']]
    values = [row['top_ten_overlap'] for row in transfer['cases']]
    colors = ['#a45334' if row['top_candidate_changes'] else '#536c55' for row in transfer['cases']]
    ax.barh(labels, values, color=colors, height=.62)
    ax.invert_yaxis()
    ax.set(xlim=(0, 10.7), xticks=range(0, 11, 2), xlabel='Candidates shared by the 500 m and 1,000 m top tens')
    for index, value in enumerate(values):
        ax.text(value+.15, index, str(value), va='center')
    image = PAPER / 'baseline-support-v11.png'
    fig.savefig(image, dpi=180)
    plt.close(fig)
    shutil.copy2(image, PUBLIC / image.name)
    payload = {'upstream': {'repository': replay['repository'], 'commit': replay['commit'],
                            'experiments_reproduced': len(replay['checks']), 'targets': replay['targets'],
                            'reference_earth_pool': replay['reference_earth_pool'], 'scope': replay['scope']},
               'adaptation': transfer, 'figure': image.name,
               'confirmatory_state': 'Source qualification incomplete; no new triad or geological discovery',
               'source_hashes': {path.name: hashlib.file_digest(path.open('rb'), 'sha256').hexdigest() for path in [replay_path, transfer_path]}}
    encoded = json.dumps(payload, indent=2, allow_nan=False) + '\n'
    (PUBLIC / 'replication_v11.json').write_text(encoded, encoding='utf-8')
    (ROOT / 'apps/web/src/generated/replication-v11.json').write_text(encoded, encoding='utf-8')
    for path in [replay_path, transfer_path]:
        shutil.copy2(path, PUBLIC / path.name)
    print('Published attributed replication, exploratory adaptation and figure')


if __name__ == '__main__':
    main()
