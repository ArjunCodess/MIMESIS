"""Resume acquisition of a frozen global frame without repeating verified tiles."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
try:
    from scripts.acquire_earth import acquire_tile
except ModuleNotFoundError:
    from acquire_earth import acquire_tile


def acquire(config_path, token_file):
    config = json.loads(config_path.read_text())
    token = token_file.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError("Earthdata token file is empty")
    sizes = {"hgt": 3601 * 3601 * 2, "swb": 3601 * 3601, "num": 3601 * 3601}
    pending, skipped = [], []
    for tile in config["tiles"]:
        folder = ROOT / "data/raw/earth/nasadem" / f"NASADEM_HGT_{tile}"
        if all(
            (folder / f"{tile}.{suffix}").exists()
            and (folder / f"{tile}.{suffix}").stat().st_size == size
            for suffix, size in sizes.items()
        ):
            skipped.append(tile)
        elif not (folder / "unavailable.json").exists():
            pending.append(tile)
    print(
        f"Verified existing tiles: {len(skipped)}; queued: {len(pending)}", flush=True
    )
    # Submit only three requests at a time; an authentication failure stops the queue.
    with ThreadPoolExecutor(max_workers=3) as pool:
        for start in range(0, len(pending), 3):
            futures = [
                pool.submit(acquire_tile, tile, token, allow_missing=True)
                for tile in pending[start : start + 3]
            ]
            for future in futures:
                future.result()
    print(
        "Frozen frame acquisition finished",
        len(config["tiles"]),
        "declared tiles",
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=ROOT / "configs/global_terrain_v8.json"
    )
    parser.add_argument("--token-file", type=Path, required=True)
    args = parser.parse_args()
    acquire(args.config, args.token_file)
