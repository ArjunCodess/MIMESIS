"""Materialize a historical JSON record excluded from Git's large-file upload.

The compressed public record is deterministic and retains the exact bytes.
Normal app/API use can read it without creating the expanded local file.
"""
import gzip
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if __name__ == '__main__':
    target = ROOT / 'apps/web/public/research/discovery.json'
    packed = target.with_suffix('.json.gz')
    if not target.exists():
        target.write_bytes(gzip.decompress(packed.read_bytes()))
    print('Historical research record ready:', target.relative_to(ROOT))
