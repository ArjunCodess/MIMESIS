"""Standalone figures from measured follow-up records and published Mars vectors."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import PathPatch, Patch
from matplotlib.path import Path as PlotPath
import numpy as np
from pyproj import CRS, Transformer
from shapely import geometry, transform
from shapely.geometry.polygon import orient

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "apps/web/public/research"
FIGURES = ROOT / "artifacts/figures"


def render():
    data = json.loads((PUBLIC / "geology_v6_jezero_mars.geojson").read_text())
    local = CRS.from_proj4("+proj=aeqd +lat_0=18.38 +lon_0=77.58 +R=3396190 +units=m")
    source = CRS.from_proj4("+proj=longlat +R=3396190 +no_defs")
    forward = Transformer.from_crs(source, local, always_xy=True)
    units = sorted(
        {
            f["properties"]["symbol"]
            for f in data["features"]
            if f["properties"].get("source_layer") == "GeoUnits_v1"
        }
    )
    colors = dict(zip(units, plt.get_cmap("Set2")(np.linspace(0, 1, len(units)))))
    fig, ax = plt.subplots(figsize=(8, 8), constrained_layout=True)
    for feature in data["features"]:
        properties = feature["properties"]
        g = transform(
            geometry.shape(feature["geometry"]), forward.transform, interleaved=False
        )
        if properties.get("source_layer") == "GeoUnits_v1":
            for polygon in g.geoms if g.geom_type == "MultiPolygon" else [g]:
                paths = []
                for ring in [
                    orient(polygon, sign=1).exterior,
                    *orient(polygon, sign=1).interiors,
                ]:
                    vertices = np.asarray(ring.coords)[:, :2] / 1000
                    codes = np.full(len(vertices), PlotPath.LINETO)
                    codes[0], codes[-1] = PlotPath.MOVETO, PlotPath.CLOSEPOLY
                    paths.append(PlotPath(vertices, codes))
                ax.add_patch(
                    PathPatch(
                        PlotPath.make_compound_path(*paths),
                        facecolor=colors[properties["symbol"]],
                        edgecolor="none",
                        alpha=0.9,
                    )
                )
        elif (
            properties.get("source_layer") == "GeoContacts"
            and properties.get("TYPE") != "boundary"
        ):
            for line in g.geoms if g.geom_type == "MultiLineString" else [g]:
                x, y = np.asarray(line.coords)[:, :2].T / 1000
                ax.plot(
                    x,
                    y,
                    color="#24362f",
                    linewidth=0.6,
                    linestyle="--" if properties["TYPE"] == "approximate" else "-",
                )
    ax.set(
        xlim=(-10, 10),
        ylim=(-10, 10),
        aspect="equal",
        xlabel="Mars local east (km)",
        ylabel="Mars local north (km)",
        title="Jezero: published geological reference at 1:75,000\nSIM3464 units and contacts in the 20 km calibration window",
    )
    ax.legend(
        handles=[Patch(facecolor=colors[u], label=u) for u in units],
        title="Published unit symbol",
        loc="lower right",
        fontsize=8,
    )
    fig.text(
        0.5,
        -0.08,
        "Source: Sun & Stack (2020), USGS SIM3464. Dashed: approximate contact.\nSource registration offsets100â€“200m; geological uncertainty is additional. No predicted contact accuracy is shown.",
        ha="center",
        fontsize=9,
    )
    fig.savefig(FIGURES / "geology_v6_jezero.png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    joined = json.loads((PUBLIC / "research_v6.json").read_text())
    old = json.loads((PUBLIC / "natural_land_v5.json").read_text())
    fig, ax = plt.subplots(figsize=(8, 4), constrained_layout=True)
    x = np.arange(2)
    ax.bar(
        x - 0.18,
        [old["experiments"][b]["eligible_count"] for b in ["500", "1000"]],
        width=0.36,
        color="#b7b49c",
        label="V5 sources",
    )
    ax.bar(
        x + 0.18,
        [b["eligible_count"] for b in joined["followup"]["buffers"]],
        width=0.36,
        color="#48644c",
        label="V6 additional HLS + available OSM",
    )
    ax.set(
        xticks=x,
        xticklabels=["500 m buffer", "1000 m buffer"],
        ylabel="Combined eligible overlapping windows",
        title="More complete source coverage changes eligibility",
    )
    ax.legend(frameon=False)
    fig.text(
        0.5,
        -0.03,
        "Fixed validity thresholds; both imagery and land-modification source coverage change.\nThese are correlated windows, not independent sites or a causal effect of imagery alone.",
        ha="center",
        fontsize=9,
    )
    fig.savefig(FIGURES / "coverage_v6_attrition.png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    for name in ["geology_v6_jezero.png", "coverage_v6_attrition.png"]:
        (PUBLIC / name).write_bytes((FIGURES / name).read_bytes())


if __name__ == "__main__":
    render()
