"""Read a research JSON record from its plain or compressed release form."""
import gzip
import json
from pathlib import Path


def asset_exists(path: Path):
    return path.exists() or path.with_suffix(path.suffix + '.gz').exists()


def read_json_asset(path: Path):
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return json.loads(gzip.decompress(path.with_suffix(path.suffix + '.gz').read_bytes()))
