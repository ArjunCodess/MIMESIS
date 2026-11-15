"""Check deterministic v5 reconstruction from frozen source-linked intermediates."""

import hashlib
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
public = ROOT / "apps/web/public/research"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--version", choices=["v5", "v6"], default="v5")
version = parser.parse_args().version
before = json.loads((public / f"natural_land_{version}.json").read_text())
base = json.loads((public / "discovery.json").read_text())
workspace = ROOT / "artifacts"
with tempfile.TemporaryDirectory(
    prefix=f"reproduction-{version}-", dir=workspace
) as directory:
    isolated = Path(directory).resolve()
    if isolated.parent != workspace.resolve():
        raise ValueError("Reproduction directory escaped artifact workspace")
    for name in ["scripts", "src", "configs"]:
        shutil.copytree(
            ROOT / name, isolated / name, ignore=shutil.ignore_patterns("__pycache__")
        )
    names = [
        "apps/web/public/research/discovery.json",
        "apps/web/public/research/bundle.json",
        "artifacts/reports/planetary_imagery.json",
        "artifacts/reports/prospective_camera_v5.json",
        "data/raw/mars/mola/megt44n000hb.img",
        "data/raw/mars/mola/megt44n000hb.xml",
    ]
    if version == "v6":
        names.append("artifacts/reports/coverage_v6.json")
    for region in base["regions"]:
        rid = region["id"]
        names += [
            f"data/processed/{rid}-projected.npz",
            f"data/processed/{rid}-human-masks{'' if version == 'v5' else '-v6'}.npz",
            f"data/raw/earth/{'human_masks' if version == 'v5' else 'human_masks_v6'}/{rid}/manifest.json",
        ]
        manifest = json.loads((ROOT / names[-1]).read_text())
        for source in manifest["worldcover_sources"]:
            if source["status"] == "acquired":
                with (ROOT / source["regional_clip"]).open("rb") as stream:
                    if (
                        hashlib.file_digest(stream, "sha256").hexdigest()
                        != source["sha256"]
                    ):
                        raise ValueError("WorldCover source checksum changed")
    for name in names:
        destination = isolated / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, destination)
    subprocess.run(
        [
            sys.executable,
            str(isolated / "scripts/build_natural_land.py"),
            "--version",
            version,
        ],
        cwd=isolated,
        env={**os.environ, "PYTHONPATH": str(isolated / "src")},
        check=True,
    )
    after = json.loads(
        (isolated / f"apps/web/public/research/natural_land_{version}.json").read_text()
    )
    for field in before:
        if field != "generated_at" and before[field] != after[field]:
            raise AssertionError(f"{version} reproduction changed {field}")
print(
    f"PASS: {version} complete masked rankings, exclusions, suppression and controls reproduce from frozen intermediates; WorldCover source checksums verified. Not a fresh raw-to-mask reconstruction."
)
