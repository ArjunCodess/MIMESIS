"""Check the files Git would publish, without staging, deleting or exposing secrets."""
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = subprocess.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT,
                            capture_output=True, check=True).stdout
    paths = sorted(set(value.decode('utf-8') for value in output.split(b'\0') if value))
    large, forbidden, suspected_secrets = [], [], []
    total = 0
    for name in paths:
        path = ROOT / name
        if not path.is_file():
            continue
        size = path.stat().st_size
        total += size
        if size > 50 * 1024**2:
            large.append({'path': name, 'bytes': size})
        if any(part in ['node_modules', '__pycache__', '.venv'] for part in path.parts) or name.startswith(('data/raw/', 'data/quarantine/')) or path.suffix.lower() in ['.rar', '.f32', '.laz', '.las']:
            forbidden.append(name)
        if path.suffix.lower() in ['.py', '.ts', '.tsx', '.js', '.json', '.yaml', '.yml', '.toml', '.env'] and size < 2_000_000:
            text = path.read_text(encoding='utf-8', errors='replace')
            if re.search(r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----|(?:ghp_|github_pat_|sk-proj-)[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}', text):
                suspected_secrets.append(name)
    result = {'candidate_file_count': len(paths), 'candidate_bytes': total,
              'over_50_mib': large, 'restricted_or_generated_paths': forbidden,
              'possible_secret_paths': suspected_secrets,
              'passes': not large and not forbidden and not suspected_secrets,
              'scope': 'Preflight of Git-visible paths and selected credential patterns, not a complete secret/history audit. No files staged or uploaded.'}
    destination = ROOT / 'artifacts/reports/github-readiness.json'
    destination.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
    return 0 if result['passes'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
