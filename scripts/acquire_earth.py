"""Acquire declared NASADEM expansion tiles with a one-use Earthdata token file."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import zipfile
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parents[1]


def acquire_tile(tile: str, token: str, allow_missing: bool = False):
    target = ROOT / "data/raw/earth/nasadem" / f"NASADEM_HGT_{tile}"
    expected = {"hgt": 3601 * 3601 * 2, "swb": 3601 * 3601, "num": 3601 * 3601}
    if all(
        (target / f"{tile}.{suffix}").exists()
        and (target / f"{tile}.{suffix}").stat().st_size == size
        for suffix, size in expected.items()
    ):
        print(f"{tile}: verified existing tile", flush=True)
        return
    target.mkdir(exist_ok=True, parents=True)
    url = f"https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/NASADEM_HGT.001/NASADEM_HGT_{tile}/NASADEM_HGT_{tile}.zip"
    temporary = target / "source.download.part"
    session = requests.Session()
    session.mount(
        "https://",
        HTTPAdapter(
            max_retries=Retry(
                total=4, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504]
            )
        ),
    )
    with (
        session,
        session.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=(30, 120),
            stream=True,
        ) as response,
    ):
        if response.status_code == 404 and allow_missing:
            (target / "unavailable.json").write_text(
                json.dumps(
                    {
                        "tile": tile,
                        "source_url": url,
                        "status": "HTTP_404",
                        "interpretation": "No product at the declared URL; not a measured zero-elevation tile",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(
                f"{tile}: unavailable product, preserved as missing coverage",
                flush=True,
            )
            return
        if response.status_code != 200:
            raise RuntimeError(
                f"Earthdata returned HTTP {response.status_code} for {tile}; credentials were not logged"
            )
        with temporary.open("wb") as stream:
            for block in response.iter_content(4 * 1024 * 1024):
                stream.write(block)
    with zipfile.ZipFile(temporary) as archive:
        if archive.testzip() is not None:
            raise ValueError(f"Corrupt NASADEM archive for {tile}")
        for suffix, size in expected.items():
            filename = f"{tile}.{suffix}"
            matches = [
                name
                for name in archive.namelist()
                if Path(name).name.lower() == filename
            ]
            if len(matches) != 1 or archive.getinfo(matches[0]).file_size != size:
                raise ValueError(f"Unexpected {filename} in NASADEM archive")
            (target / filename).write_bytes(archive.read(matches[0]))
    temporary.replace(target / f"NASADEM_HGT_{tile}.zip")
    (target / "acquisition.json").write_text(
        json.dumps(
            {
                "tile": tile,
                "source_url": url,
                "authentication": "Earthdata bearer; credential not retained",
                "archive_integrity": "CRC checked",
                "members": expected,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"{tile}: acquired and verified", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--token-file", type=Path, required=True)
    args = parser.parse_args()
    credential = args.token_file.read_text(encoding="utf-8").strip()
    config = json.loads((ROOT / "configs/expansion.json").read_text())
    tiles = list(
        dict.fromkeys(tile for region in config["regions"] for tile in region["tiles"])
    )
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda tile: acquire_tile(tile, credential), tiles))
