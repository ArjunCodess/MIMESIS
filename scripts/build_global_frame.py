"""Freeze a climate sampling frame; optional NASADEM acquisition is explicitly bounded."""

import argparse
from collections import Counter
from contextlib import ExitStack
import csv
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

import rasterio
from src.climate import (
    ClimateRasters,
    SamplingDesign,
    freeze_frame,
    parse_koppen_legend,
    summarize_context,
)

ROOT = Path(__file__).resolve().parents[1]


def digest(path, algorithm="sha256"):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def build(config_path):
    config = json.loads(config_path.read_text(encoding="utf-8"))
    design = SamplingDesign.model_validate(config["sampling"])
    raw = ROOT / "data/raw/earth/global_climate"
    provenance = []
    for source in config["sources"]:
        archive_path = ROOT / source["archive"]
        if (
            archive_path.stat().st_size != source["archive_bytes"]
            or digest(archive_path, "md5") != source["archive_md5"]
        ):
            raise ValueError(f"Source archive integrity mismatch: {source['id']}")
        members = []
        with zipfile.ZipFile(archive_path) as archive:
            for name in source["members"]:
                target = raw / source["id"] / name
                target.parent.mkdir(parents=True, exist_ok=True)
                # Explicit allowlisted members only; fresh extraction verifies archive CRC.
                with archive.open(name) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                members.append(
                    {
                        "member": name,
                        "bytes": target.stat().st_size,
                        "sha256": digest(target),
                    }
                )
        provenance.append(
            {
                **source,
                "archive_sha256": digest(archive_path),
                "integrity": "declared byte count and MD5 verified; selected member CRC verified",
                "extracted_members": members,
            }
        )
    annual = raw / "global_ai_et0_v31/Global-AI_ET0__annual_v3_1"
    historical = raw / "koppen_geiger_v2"
    legend = parse_koppen_legend(
        (historical / "legend.txt").read_text(encoding="utf-8-sig")
    )
    with ExitStack() as stack:
        paths = [
            annual / "ai_v31_yr.tif",
            annual / "et0_v31_yr.tif",
            historical / "1991_2020/koppen_geiger_0p00833333.tif",
        ]
        datasets = [stack.enter_context(rasterio.open(path)) for path in paths]
        rasters = ClimateRasters(*datasets, legend)
        result = freeze_frame(design, rasters.points, config["known_controls"])
        for block in result["blocks"]:
            block["context_climate"] = summarize_context(
                block, rasters, config["context_summary_spacing_m"], design.ai_maximum
            )
        regions = json.loads((ROOT / config["current_regions"]).read_text())["regions"]
        current_regions = [
            {
                "id": r["id"],
                "name": r["name"],
                "center_climate": rasters.points([[r["longitude"], r["latitude"]]])[0],
                "climate_summary": rasters.region_summary(
                    r["bounds"], design.ai_maximum
                ),
            }
            for r in regions
        ]
        raster_metadata = [
            {
                "name": p.name,
                "crs": str(d.crs),
                "shape": list(d.shape),
                "transform": list(d.transform),
                "nodata": d.nodata,
                "dtype": d.dtypes[0],
            }
            for p, d in zip(paths, datasets)
        ]
    block_tiles = {
        tile for block in result["blocks"] for tile in block["nasadem_tiles"]
    }
    tiles = [
        {
            "tile": tile,
            "block_ids": [
                b["id"] for b in result["blocks"] if tile in b["nasadem_tiles"]
            ],
            "url": f"https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/NASADEM_HGT.001/NASADEM_HGT_{tile}/NASADEM_HGT_{tile}.zip",
            "status": "not_requested_remote_availability_unverified",
            "expected_members": {
                f"{tile}.hgt": 3601 * 3601 * 2,
                f"{tile}.swb": 3601 * 3601,
                f"{tile}.num": 3601 * 3601,
            },
        }
        for tile in sorted(block_tiles)
    ]
    manifest = {
        "source_family": "NASADEM_HGT.001",
        "unique_tile_count": len(tiles),
        "block_tile_reference_count": sum(
            len(b["nasadem_tiles"]) for b in result["blocks"]
        ),
        "uncompressed_required_member_bytes": len(tiles) * 3601 * 3601 * 4,
        "availability": "geometric manifest only, remote availability and valid terrain support unverified",
        "tiles": tiles,
    }
    frame = {
        "id": config["id"],
        "schema_version": config["schema_version"],
        "status": "sampled_climate_frame_not_measured_null_or_discovery",
        "scope": config["scope"],
        "config_sha256": digest(config_path),
        "sampling": config["sampling"],
        "selection_contract": config["selection_contract"],
        "selection": {
            "requested_count": sum(s.count for s in design.strata),
            "accepted_count": len(result["blocks"]),
            "attempted_count": len(result["attempts"]),
            "maximum_attempts": design.maximum_attempts,
            "unfilled_count": result["unfilled_count"],
            "stratum_counts": result["stratum_counts"],
            "exclusion_counts": dict(
                sorted(Counter(a["reason"] for a in result["attempts"]).items())
            ),
        },
        "blocks": result["blocks"],
        "current_regions": current_regions,
        "known_controls": config["known_controls"],
        "sources": provenance,
        "native_rasters": raster_metadata,
        "koppen_legend": legend,
        "koppen_confidence": {
            "status": "unavailable_in_supplied_archive",
            "used_for_selection": False,
        },
        "acquisition_manifest": {k: v for k, v in manifest.items() if k != "tiles"},
        "restrictions": config["restrictions"],
    }
    # JSON object keys are strings on disk, including numeric legend codes.
    # Normalize them before canonical sorting so readers can reproduce the hash.
    frame = json.loads(json.dumps(frame, allow_nan=False))
    frame["frame_sha256"] = hashlib.sha256(
        json.dumps(
            frame, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    write_json(ROOT / "data/metadata/global_frame_v6.json", frame)
    write_json(ROOT / "data/metadata/global_nasadem_manifest_v6.json", manifest)
    write_json(
        ROOT / "data/processed/global_frame_v6.geojson",
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": b["geometry"],
                    "properties": {k: v for k, v in b.items() if k != "geometry"},
                }
                for b in result["blocks"]
            ],
        },
    )
    attempt_path = ROOT / "data/processed/global_frame_attempts_v6.csv"
    with attempt_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(result["attempts"][0]))
        writer.writeheader()
        writer.writerows(result["attempts"])
    public = ROOT / "apps/web/public/research"
    write_json(public / "global_frame_v6.json", frame)
    write_json(public / "global_nasadem_manifest_v6.json", manifest)
    report = ROOT / "artifacts/reports/global_frame_v6.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        f"# Global climate sampling frame v6\n\nSelected {len(result['blocks'])} nonoverlapping 80 km contexts from {len(result['attempts'])} equal-area proposals. Strata: {result['stratum_counts']}. Unfilled: {result['unfilled_count']}.\n\nThis is a sampled climate frame. Terrain has not been acquired or measured, and these blocks establish no terrain null or analogue discovery. Eligibility uses center climate; context summaries do not change membership.\n\nThe exact geometric NASADEM manifest contains {len(tiles)} unique tiles. Remote availability remains unverified. Acquisition requires an explicit token file and a finite tile limit.\n\nAI raw values are multiplied by 0.0001, ET0 is mm/year, both cover 1970-2000. Koppen uses 1991-2020; the supplied archive has no confidence raster. Archive hashes, member hashes, the parsed legend, native raster metadata, exclusions and current-region climate summaries are retained in the JSON/CSV artifacts.\n\nAI metadata says CC BY 4.0 while the supplied readme says noncommercial use and commercial permission. Raw inputs remain local and are excluded from publication.\n\nFrame SHA256: `{frame['frame_sha256']}`.\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "selection": frame["selection"],
                "manifest": frame["acquisition_manifest"],
                "frame_sha256": frame["frame_sha256"],
            },
            indent=2,
        )
    )
    if result["unfilled_count"]:
        raise SystemExit(
            "Finite proposal budget exhausted; partial frame retained without replacement"
        )


def acquire(token_file, max_tiles):
    if not 1 <= max_tiles <= 20:
        raise ValueError("Explicit --max-tiles must be between 1 and 20 per invocation")
    manifest = json.loads(
        (ROOT / "data/metadata/global_nasadem_manifest_v6.json").read_text()
    )
    from acquire_earth import acquire_tile
    import requests

    token = token_file.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError("Token file is empty")
    # Sequential, capped work; credentials are never stored in public artifacts.
    pending = []
    for entry in manifest["tiles"]:
        directory = ROOT / "data/raw/earth/nasadem" / f"NASADEM_HGT_{entry['tile']}"
        complete = all(
            (directory / name).is_file() and (directory / name).stat().st_size == size
            for name, size in entry["expected_members"].items()
        )
        if not complete and not (directory / "unavailable.json").exists():
            pending.append(entry["tile"])
    attempted = []
    blocked = None
    for tile in pending[:max_tiles]:
        attempted.append(tile)
        try:
            acquire_tile(tile, token, allow_missing=True)
        except (
            requests.RequestException,
            RuntimeError,
            ValueError,
            zipfile.BadZipFile,
            OSError,
        ) as error:
            # Retain only the error type: upstream exceptions can contain request headers.
            blocked = {
                "tile": tile,
                "error_type": type(error).__name__,
                "status": "blocked_acquisition_stopped",
            }
            break
    statuses = []
    for entry in manifest["tiles"]:
        directory = ROOT / "data/raw/earth/nasadem" / f"NASADEM_HGT_{entry['tile']}"
        complete = all(
            (directory / name).is_file() and (directory / name).stat().st_size == size
            for name, size in entry["expected_members"].items()
        )
        state = (
            "members_present_terrain_unmeasured"
            if complete
            else "missing_remote_product"
            if (directory / "unavailable.json").exists()
            else "not_acquired"
        )
        statuses.append({"tile": entry["tile"], "status": state})
    report = {
        "status": "blocked" if blocked else "bounded_acquisition_finished",
        "terrain_status": "unmeasured_not_a_terrain_null",
        "maximum_requested_tiles": max_tiles,
        "attempted_tiles": attempted,
        "blocked": blocked,
        "tile_status_counts": dict(Counter(entry["status"] for entry in statuses)),
        "tiles": statuses,
    }
    write_json(ROOT / "data/metadata/global_nasadem_acquisition_v6.json", report)
    write_json(
        ROOT / "apps/web/public/research/global_nasadem_acquisition_v6.json", report
    )
    print(json.dumps({k: v for k, v in report.items() if k != "tiles"}, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=ROOT / "configs/global_frame_v6.json"
    )
    parser.add_argument(
        "--acquire-nasadem",
        action="store_true",
        help="Acquire at most the explicit tile limit from the frozen manifest",
    )
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--max-tiles", type=int)
    args = parser.parse_args()
    if args.acquire_nasadem:
        if args.token_file is None or args.max_tiles is None:
            parser.error(
                "--acquire-nasadem requires --token-file and an explicit --max-tiles between 1 and 20"
            )
        acquire(args.token_file, args.max_tiles)
    else:
        if args.max_tiles is not None or args.token_file is not None:
            parser.error("--token-file and --max-tiles require --acquire-nasadem")
        build(args.config)
