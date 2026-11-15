"""Rebuild frozen v4 in isolation so later acquisitions cannot change its domain."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
before = json.loads((ROOT / "apps/web/public/research/discovery.json").read_text())
workspace = ROOT / "artifacts"
with tempfile.TemporaryDirectory(prefix="reproduction-v4-", dir=workspace) as directory:
    isolated = Path(directory).resolve()
    if isolated.parent != workspace.resolve():
        raise ValueError("Reproduction directory escaped the artifact workspace")
    for name in ["scripts", "src", "configs"]:
        shutil.copytree(
            ROOT / name, isolated / name, ignore=shutil.ignore_patterns("__pycache__")
        )
    for name in ["data/processed", "artifacts/reports", "apps/web/public/research"]:
        (isolated / name).mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        ROOT / "apps/web/public/research/bundle.json",
        isolated / "apps/web/public/research/bundle.json",
    )
    sources = set()
    for item in before["source_manifest"]:
        source = ROOT / item["path"]
        if source.stat().st_size != item["bytes"]:
            raise ValueError(f"Source size changed: {item['path']}")
        with source.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != item["sha256"]:
                raise ValueError(f"Source checksum changed: {item['path']}")
        sources.add(source)
        if source.suffix == ".img":
            sources.add(source.with_suffix(".xml"))
        sources.update(source.parent.glob("*stac.json"))
    for source in sorted(sources):
        target = isolated / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    environment = {**os.environ, "PYTHONPATH": str(isolated / "src")}
    subprocess.run(
        [sys.executable, str(isolated / "scripts/build_discovery.py"), "--fresh"],
        cwd=isolated,
        env=environment,
        check=True,
    )
    after = json.loads(
        (isolated / "apps/web/public/research/discovery.json").read_text()
    )
    for field in [
        "protocol_hash",
        "data_hash",
        "record_hash",
        "implementation_hash",
        "runs",
        "suites",
        "investigations",
        "benchmark",
        "requirement_coverages",
    ]:
        if before[field] != after[field]:
            raise AssertionError(
                f"Fresh raw-source discovery reproduction changed {field}"
            )
print(
    "PASS: isolated frozen-source v4 rebuild reproduces complete rankings, selections and hashes; published files untouched"
)
