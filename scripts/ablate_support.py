"""Remove Gaussian support matching while holding domain, weights and cutoffs fixed."""

from copy import deepcopy
import json
from pathlib import Path
import numpy as np
from scipy.ndimage import map_coordinates
from src.terrain import features, open_pds, project_window
from src.ranking import rank

ROOT = Path(__file__).resolve().parents[1]


def ablate():
    data = json.loads((ROOT / "apps/web/public/research/discovery.json").read_text())
    candidates = deepcopy(data["candidates"])
    fields = {r["id"]: np.load(ROOT / f"data/processed/{r['id']}-projected.npz")["elevation"] for r in data["regions"]}
    axis = np.arange(-39750, 40000, 500)
    for candidate in candidates:
        x, y = np.meshgrid(axis + candidate["easting_m"], -axis + candidate["northing_m"])
        grid = map_coordinates(fields[candidate["region_id"]], [(116000 - y) / 125 - .5, (x + 116000) / 125 - .5], order=1, mode="constant", cval=np.nan)
        candidate["features"]["500"] = features(grid, 500)
        candidate["features"]["eroded"] = features(grid, 500, erode=True)
    results = []
    for original in data["targets"]:
        target = deepcopy(original)
        mars = target["body"] == "Mars"
        stem = "data/raw/mars/mola/megt44n000hb" if mars else "data/raw/moon/lola/ldem_64"
        source = open_pds(ROOT / f"{stem}.img", ROOT / f"{stem}.xml", "mola" if mars else "lola")
        projected, _ = project_window(source, target["latitude"], target["longitude"], 80000, 125)
        indices = np.arange(1.5, len(projected), 4)
        yy, xx = np.meshgrid(indices, indices, indexing="ij")
        grid = map_coordinates(projected, [yy, xx], order=1, mode="constant", cval=np.nan)
        target["features"]["500"] = features(grid, 500)
        target["features"]["eroded"] = features(grid, 500, erode=True)
        task = data["tasks"]["tasks"][0]
        protocol = {**data["protocol"], "task": task["id"], "task_version": task["version"], "weights": task["weights"], "ablation": "No Gaussian smoothing at 500m or eroded tier; 1km sensitivity held fixed"}
        result = rank(candidates, target, protocol)
        baseline = data["runs"][task["id"]][target["id"]]["500"]
        left = {r["id"] for r in baseline["candidates"][:10]}
        right = {r["id"] for r in result["candidates"][:10]}
        results.append({"target_id": target["id"], "baseline_winner": baseline["candidates"][0]["id"], "unsmoothed_winner": result["candidates"][0]["id"], "top10_jaccard": len(left & right) / len(left | right), "run_hash": result["run_hash"], "excluded_count": result["excluded_count"], "candidates": result["candidates"], "interpretation": "Sensitivity to Gaussian support treatment; projected staging still uses bilinear sampling. This is not a claim of superior science without independent relevance labels."})
        print(target["id"], results[-1]["top10_jaccard"], flush=True)
    (ROOT / "artifacts/reports/support_ablation.json").write_text(json.dumps(results), encoding="utf-8")


if __name__ == "__main__":
    ablate()
