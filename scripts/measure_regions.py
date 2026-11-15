"""Bounded, predeclared multi-region Earth measurements for the v2 expansion."""

import json
import numpy as np
from PIL import Image
from scipy.ndimage import map_coordinates
from src.terrain import open_nasadem_mosaic, project_window, smooth_grid, features
from src.imagery import hls_context


def measure_regions(root, protocol, expansion, render):
    public = root / "apps/web/public/research"
    candidates = []
    contexts = {}
    regions = []
    reserved = []
    attempted = 0
    region_coverages = []
    extent = expansion["extent_m"]
    half = extent / 2
    for definition in expansion["regions"]:
        identifier = definition["id"]
        raster = open_nasadem_mosaic(
            root / "data/raw/earth/nasadem",
            definition["tiles"],
            root / f"data/processed/{identifier}-mosaic.hgt",
        )
        field, inverse = project_window(
            raster, definition["latitude"], definition["longitude"], extent, 125
        )
        fields = {str(s): smooth_grid(field, 125, s) for s in [500, 1000]}
        np.savez_compressed(
            root / f"data/processed/{identifier}-projected.npz",
            elevation=field,
            spacing_m=125,
        )
        for support in [500, 1000]:
            render(fields[str(support)], public / f"{identifier}-{support}.png", True)
        imagery_mask = np.zeros(field.shape, dtype=bool)
        composite = np.full((*field.shape, 3), [230, 226, 214], dtype=np.uint8)
        scene_records = []
        metadata_paths = sorted((root / "data/raw/earth/hls").rglob("*stac.json"))
        for path in metadata_paths:
            meta = json.loads(path.read_text())
            west, south, east, north = meta["bbox"]
            region_w, region_s, region_e, region_n = definition["bounds"]
            if (
                east < region_w
                or west > region_e
                or north < region_s
                or south > region_n
            ):
                continue
            if not all(
                list(path.parent.glob(f"*{band}.tiff"))
                for band in ["B02", "B03", "B04", "Fmask"]
            ):
                continue
            good, record = hls_context(
                path.parent,
                inverse,
                public / f"{identifier}-{meta['id']}-context.png",
                extent,
            )
            values = np.asarray(Image.open(public / record["image"]).convert("RGB"))
            composite[good] = values[good]
            imagery_mask |= good
            scene_records.append(record)
        Image.fromarray(composite).save(public / f"{identifier}-hls.png")
        region_coverages.append(float(imagery_mask.mean()))
        # The independent imagery is not used in rank eligibility or descriptors.
        start = len(candidates)
        search = range(
            -expansion["search_half_extent_m"],
            expansion["search_half_extent_m"] + 1,
            expansion["stride_m"],
        )
        for northing in search:
            for easting in search:
                attempted += 1
                measured = {}
                windows = {}
                for support in [500, 1000]:
                    axis = np.arange(-40000 + support / 2, 40000, support)
                    x, y = np.meshgrid(axis + easting, -axis + northing)
                    rows = (half - y) / 125 - 0.5
                    cols = (x + half) / 125 - 0.5
                    window = map_coordinates(
                        fields[str(support)],
                        [rows, cols],
                        order=1,
                        mode="constant",
                        cval=np.nan,
                    )
                    measured[str(support)] = features(
                        window, support, protocol["minimum_valid_fraction"]
                    )
                    windows[str(support)] = window
                measured["eroded"] = features(
                    windows["500"], 500, protocol["minimum_valid_fraction"], True
                )
                if not all(measured.values()):
                    continue
                lon, lat = inverse.transform(easting, northing)
                footprint = [
                    inverse.transform(easting + dx, northing + dy)
                    for dx, dy in [
                        (-10000, -10000),
                        (10000, -10000),
                        (10000, 10000),
                        (-10000, 10000),
                        (-10000, -10000),
                    ]
                ]
                cid = f"{identifier.upper()}-{easting + 100000:06d}-{northing + 100000:06d}"
                row = int((half - northing) / 125)
                col = int((half + easting) / 125)
                local_cover = float(
                    imagery_mask[row - 80 : row + 80, col - 80 : col + 80].mean()
                )
                context_cover = float(
                    imagery_mask[row - 320 : row + 320, col - 320 : col + 320].mean()
                )
                candidates.append(
                    {
                        "id": cid,
                        "name": f"{definition['name']} study window",
                        "region": definition["name"],
                        "region_id": identifier,
                        "latitude": lat,
                        "longitude": lon,
                        "easting_m": easting,
                        "northing_m": northing,
                        "footprint": footprint,
                        "features": measured,
                        "source_ids": ["nasadem"],
                        "image": f"{identifier}-500.png",
                        "reserved_hls_valid_fraction": local_cover,
                        "hls_context_valid_fraction": context_cover,
                        "imagery_scene_ids": [r["scene_id"] for r in scene_records],
                    }
                )
                contexts[cid] = windows["500"].astype(np.float32)
            if northing % 15000 == 0:
                print(
                    f"{identifier}: sweep {northing:+} m, {len(candidates) - start} valid windows",
                    flush=True,
                )
        # Preserve composite in a projected grid to create exact candidate evidence panels later.
        np.savez_compressed(
            root / f"data/processed/{identifier}-imagery.npz",
            rgb=composite,
            valid=imagery_mask,
            spacing_m=125,
            extent_m=extent,
        )
        regions.append(
            {
                **definition,
                "center": [definition["longitude"], definition["latitude"]],
                "tile": ", ".join(definition["tiles"]),
                "extent_m": extent,
                "image": f"{identifier}-500.png",
                "image_1000": f"{identifier}-1000.png",
                "imagery_image": f"{identifier}-hls.png",
                "valid_windows": len(candidates) - start,
                "attempted_windows": len(search) ** 2,
                "stride_m": expansion["stride_m"],
                "projection": f"WGS84 AEQD centered {definition['latitude']}, {definition['longitude']}",
                "independence": "Overlapping 20 km windows are not independent samples",
            }
        )
        reserved.extend(scene_records)
        print(
            f"{identifier}: {len(candidates) - start} terrain windows; {len(scene_records)} separate HLS scenes",
            flush=True,
        )
    record = {
        "scene_id": "multi-scene HLS expansion",
        "acquired_at": min((r["acquired_at"] for r in reserved), default=None),
        "mask_rule": "Exclude fill and HLS Fmask bits 0 through 5; union valid coverage across scenes",
        "display": "RGB B04/B03/B02; reflectance/0.4, gamma 1/2.2",
        "image": regions[0]["imagery_image"],
        "interpreted": False,
        "role": "reserved_context",
        "valid_projected_grid_fraction": float(np.mean(region_coverages)),
        "scenes": reserved,
    }
    return candidates, contexts, regions, record, attempted
