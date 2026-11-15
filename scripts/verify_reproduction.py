"""Rebuild from source bytes and require all exported scientific ranks to agree."""

from pathlib import Path
import json
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
path = root / "apps/web/public/research/bundle.json"
before = json.loads(path.read_text(encoding="utf-8"))
subprocess.run(
    [sys.executable, str(root / "scripts/build_research.py"), "--expanded"],
    cwd=root,
    check=True,
)
after = json.loads(path.read_text(encoding="utf-8"))
for field in (
    "protocol_hash",
    "data_hash",
    "rankings",
    "rankings_1000",
    "benchmark",
    "investigations",
):
    if before[field] != after[field]:
        raise AssertionError(f"Source-to-export reproduction changed {field}")
print(
    "PASS: protocol, source hashes, both complete ranking tiers, benchmarks and frozen investigations reproduce exactly"
)
