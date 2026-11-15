"""Acquire the declared public Puga or Jezero sources with archive checksums."""

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parents[1]


def acquire_file(session, url, path, size, algorithm, checksum):
    if path.is_file() and path.stat().st_size == size:
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, algorithm).hexdigest() == checksum:
                print("Verified", path.name, flush=True)
                return
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    digest = hashlib.new(algorithm)
    with session.get(url, timeout=(30, 120), stream=True) as response:
        response.raise_for_status()
        with partial.open("wb") as stream:
            for chunk in response.iter_content(1024 * 1024):
                digest.update(chunk)
                stream.write(chunk)
    if partial.stat().st_size != size or digest.hexdigest() != checksum:
        raise ValueError(f"Source checksum/size mismatch: {path.name}")
    partial.replace(path)
    print("Acquired", path.name, flush=True)


def acquire(dataset):
    with requests.Session() as session:
        session.mount(
            "https://",
            HTTPAdapter(
                max_retries=Retry(
                    total=4,
                    backoff_factor=1,
                    status_forcelist=[429, 500, 502, 503, 504],
                )
            ),
        )
        if dataset == "puga":
            config = json.loads((ROOT / "configs/puga_control_v6.json").read_text())
            for declared in config["records"]:
                folder = ROOT / config["source_root"] / declared["id"]
                metadata = folder / "record.json"
                if metadata.exists():
                    record = json.loads(metadata.read_text())
                else:
                    response = session.get(
                        f"https://zenodo.org/api/records/{declared['id']}",
                        timeout=(30, 120),
                    )
                    response.raise_for_status()
                    record = response.json()
                if (
                    str(record["id"]) != declared["id"]
                    or len(record["files"]) != declared["expected_file_count"]
                ):
                    raise ValueError(
                        "Zenodo record identity/file count differs from frozen protocol"
                    )
                folder.mkdir(parents=True, exist_ok=True)
                if not metadata.exists():
                    metadata.write_text(json.dumps(record, indent=2), encoding="utf-8")
                for item in record["files"]:
                    name = item["key"]
                    if Path(name).name != name:
                        raise ValueError("Expected a flat archive filename")
                    algorithm, checksum = item["checksum"].split(":", 1)
                    acquire_file(
                        session,
                        item["links"]["self"],
                        folder / name,
                        item["size"],
                        algorithm,
                        checksum,
                    )
        else:
            config = json.loads((ROOT / "configs/geology_v6.json").read_text())
            folder = ROOT / config["raw_directory"]
            for item in config["source"]["files"]:
                acquire_file(
                    session,
                    config["source"]["download_base_url"] + item["name"],
                    folder / item["name"],
                    item["bytes"],
                    "sha256",
                    item["sha256"],
                )
            with zipfile.ZipFile(folder / "sim3464_database.zip") as archive:
                if archive.testzip() is not None:
                    raise ValueError("Corrupt geological database archive")
                for member in archive.infolist():
                    destination = (folder / member.filename).resolve()
                    if not destination.is_relative_to(folder.resolve()):
                        raise ValueError("Archive path escapes source directory")
                if not (folder / config["source"]["geodatabase"]).exists():
                    archive.extractall(folder)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", choices=["puga", "jezero-geology"])
    acquire(parser.parse_args().dataset)
