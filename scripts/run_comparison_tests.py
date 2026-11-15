"""Run bounded upstream numerical tests and retain their exact receipts."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    inventory = json.loads((ROOT / 'artifacts/reports/submission-audit-2026-11-15/repositories.json').read_text())
    receipts = []
    for repo, relative, python_directory in [
        ('end13s/analog-atlas', 'engine/tests', 'engine'),
        ('shishir-kuet/terrestrial-analog-finder', 'backend/tests/test_similarity.py', 'backend')]:
        entry = next(row for row in inventory if row['repo'] == repo)
        folder = ROOT / 'data/raw/comparison_sources' / repo / entry['head']
        if not (folder / relative).exists():
            raise ValueError('Acquire the pinned comparison sources before running their tests: ' + repo)
        environment = os.environ.copy()
        environment['PYTHONPATH'] = str(folder / python_directory)
        result = subprocess.run(['python', '-m', 'pytest', relative, '-q'], cwd=folder, env=environment,
                                capture_output=True, text=True)
        receipts.append({'repository': 'https://github.com/' + repo, 'commit': entry['head'],
                         'test_path': relative, 'exit_code': result.returncode,
                         'stdout': result.stdout, 'stderr': result.stderr,
                         'scope': 'Upstream numerical software tests; not raw observation or geological validation'})
        print(repo, result.stdout.strip(), flush=True)
    output = ROOT / 'artifacts/reports/replication_v11/upstream_tests.json'
    output.write_text(json.dumps(receipts, indent=2) + '\n', encoding='utf-8')
    return 0 if all(row['exit_code'] == 0 for row in receipts) else 1


if __name__ == '__main__':
    raise SystemExit(main())
