"""Acquire pinned public source snapshots for local review and replication.

Snapshots stay under ignored data/raw. Acquisition does not grant redistribution
rights or establish that any reported scientific result is correct.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / 'artifacts/reports/submission-audit-2026-11-15/repositories.json'
OUT = ROOT / 'data/raw/comparison_sources'
EXTENSIONS = {'.py', '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.json',
              '.yaml', '.yml', '.md', '.txt', '.toml', '.css', '.scss', '.html',
              '.sh', '.ps1', '.sql', '.csv'}


def acquire_repository(record):
    repo, revision = record['repo'], record['head']
    folder = OUT / repo / revision
    folder.mkdir(parents=True, exist_ok=True)
    tree_path = ROOT / 'artifacts/reports/submission-audit-2026-11-15' / repo.split('/')[0] / 'tree.json'
    tree = json.loads(tree_path.read_text(encoding='utf-8'))
    files = [row for row in tree['tree'] if row['type'] == 'blob'
             and (Path(row['path']).suffix.lower() in EXTENSIONS or Path(row['path']).name in ['LICENSE', 'NOTICE', 'Dockerfile'])
             and row.get('size', 0) <= 2_000_000]

    def download(row):
        relative = Path(row['path'])
        path = folder / relative
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Unsafe source tree path')
        path.parent.mkdir(parents=True, exist_ok=True)
        url = 'https://raw.githubusercontent.com/' + repo + '/' + revision + '/' + quote(row['path'])
        if not path.exists():
            if row.get('size') == 0:
                path.write_bytes(b'')
            else:
                response = requests.get(url, timeout=60)
                response.raise_for_status()
                path.write_bytes(response.content)
        content = path.read_bytes()
        actual_blob = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
        if actual_blob != row['sha']:
            raise ValueError('Git blob mismatch: ' + repo + '/' + row['path'])
        return {'path': row['path'], 'bytes': len(content), 'git_blob': actual_blob,
                'sha256': hashlib.sha256(content).hexdigest()}

    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts = list(pool.map(download, files))
    manifest = {'repository': repo, 'commit': revision,
                'license_detected': record.get('license'),
                'scope': 'Source/text/data files at most 2 MB each; binary media and large payloads omitted',
                'files': receipts, 'not_claimed': ['full application execution', 'result verification', 'scientific novelty']}
    (folder / '_snapshot.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(repo, len(receipts), 'verified source files', flush=True)
    return {'repository': repo, 'commit': revision, 'files': len(receipts),
            'manifest': (folder / '_snapshot.json').relative_to(ROOT).as_posix()}


if __name__ == '__main__':
    records = [row for row in json.loads(INVENTORY.read_text()) if row['status'] == 200]
    results = []
    # Repositories are sequential; each owns a bounded concurrent download pool.
    for record in records:
        results.append(acquire_repository(record))
        destination = ROOT / 'data/metadata/comparison_source_snapshots.json'
        destination.write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
