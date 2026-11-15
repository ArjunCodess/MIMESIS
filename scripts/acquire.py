"""Repair interrupted public PDS downloads; preserve supplied partial bytes."""

from pathlib import Path
import argparse
import requests

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "mola": (
        "data/raw/mars/mola/megt44n000hb.img",
        "https://pds-geosciences.wustl.edu/mgs/urn-nasa-pds-mgs_mola_topography_derived/meg128/megt44n000hb.img",
        5632 * 11520 * 2,
    ),
    "lola": (
        "data/raw/moon/lola/ldem_64.img",
        "https://imbrium.mit.edu/DATA/LOLA_GDR/CYLINDRICAL/IMG/LDEM_64.IMG",
        11520 * 23040 * 2,
    ),
}


def acquire(key: str):
    relative, url, expected = SOURCES[key]
    path = ROOT / relative
    if path.exists() and path.stat().st_size == expected:
        print(f"{key}: complete ({expected:,} bytes)", flush=True)
        return
    temporary = path.with_suffix(".download.part")
    # Supplied browser .part files have no verified range origin. Never append them.
    with requests.get(url, stream=True, timeout=(30, 120)) as response:
        response.raise_for_status()
        with temporary.open("wb") as output:
            for chunk in response.iter_content(4 * 1024 * 1024):
                output.write(chunk)
    if temporary.stat().st_size != expected:
        raise ValueError(
            f"{key}: expected {expected} bytes, received {temporary.stat().st_size}"
        )
    temporary.replace(path)
    print(f"{key}: acquired {expected:,} bytes with TLS verification", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "sources", nargs="*", default=list(SOURCES), choices=list(SOURCES)
    )
    for source in parser.parse_args().sources:
        acquire(source)
