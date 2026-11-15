"""Create source-linked frozen candidate image panels without changing a rank."""

from pathlib import Path
import json
import numpy as np
from PIL import Image
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "apps/web/public/research"


def prepare(
    bundle_name="bundle.json", packet_name="evidence_packets.json", figure_prefix=""
):
    bundle = json.loads((PUBLIC / bundle_name).read_text())
    lookup = {c["id"]: c for c in bundle["candidates"]}
    imagery = {
        r["target_id"]: r
        for r in json.loads(
            (ROOT / "artifacts/reports/planetary_imagery.json").read_text()
        )
    }
    fields = {
        r["id"]: np.load(ROOT / f"data/processed/{r['id']}-imagery.npz")
        for r in bundle["regions"]
    }
    packets = []
    for target in bundle["targets"]:
        investigation = bundle["investigations"][target["id"]]
        fig, axes = plt.subplots(2, 4, figsize=(20, 11), facecolor="#f5f2e9")
        axes = axes.ravel()
        source = imagery[target["id"]]
        if source["status"] == "acquired" and source["valid_alpha_fraction"] > 0.95:
            axes[0].imshow(
                Image.open(PUBLIC / source["image"]), extent=(-40, 40, -40, 40)
            )
            axes[0].add_patch(
                Rectangle((-10, -10), 20, 20, fill=False, edgecolor="#e9ac4c", lw=1)
            )
        else:
            axes[0].text(
                0.5,
                0.5,
                "Separate camera view unavailable\nSee source record for the acquisition failure.",
                ha="center",
                va="center",
                transform=axes[0].transAxes,
            )
        axes[0].set_title(target["name"] + " | separate camera image", fontsize=12)
        for i, dossier in enumerate(investigation["shortlist"], start=1):
            candidate = lookup[dossier["candidate_id"]]
            field = fields[candidate["region_id"]]
            half = float(field["extent_m"]) / 2
            row = int((half - candidate["northing_m"]) / 125)
            col = int((half + candidate["easting_m"]) / 125)
            rgb = field["rgb"][row - 320 : row + 320, col - 320 : col + 320]
            name = f"{candidate['id']}-optical.png"
            Image.fromarray(rgb).save(PUBLIC / name)
            axes[i].imshow(rgb, extent=(-40, 40, -40, 40))
            axes[i].add_patch(
                Rectangle((-10, -10), 20, 20, fill=False, edgecolor="#e9ac4c", lw=1)
            )
            axes[i].set_title(
                f"{candidate['id']}\n{dossier['role']}; local {candidate['reserved_hls_valid_fraction']:.1%}, context {candidate['hls_context_valid_fraction']:.1%}",
                fontsize=9,
            )
            packets.append(
                {
                    "target_id": target["id"],
                    "candidate_id": candidate["id"],
                    "role": dossier["role"],
                    "earth_image": name,
                    "planetary_image": source.get("image"),
                    "earth_local_clear_fraction": candidate[
                        "reserved_hls_valid_fraction"
                    ],
                    "earth_context_clear_fraction": candidate[
                        "hls_context_valid_fraction"
                    ],
                    "planetary_valid_fraction": source.get("valid_alpha_fraction", 0),
                    "source_scene_ids": candidate["imagery_scene_ids"],
                    "source_planetary_id": source.get("source_id"),
                    "inspection_status": "not_assessed",
                    "run_hash": investigation["run_hash"],
                }
            )
        axes[-1].axis("off")
        for unused in axes[len(investigation["shortlist"]) + 1 : -1]:
            unused.axis("off")
        axes[-1].text(
            0,
            0.95,
            "80 km image context; centered 20 km footprint\nPale Earth pixels are missing or masked.\nOptical contrast is not a measured slope.\nNo ranks or losses shown in this assessment sheet.\n\nModel-assisted interpretation; no external reviewer.",
            va="top",
            fontsize=12,
        )
        for ax in axes[:-1]:
            ax.set_xlabel("Local east, km", fontsize=8)
            ax.set_ylabel("Local north, km", fontsize=8)
            ax.tick_params(labelsize=7)
        fig.suptitle(
            f"MIMESIS frozen imagery investigation | {target['name']}", fontsize=18
        )
        fig.tight_layout()
        fig.savefig(
            ROOT
            / f"artifacts/figures/{figure_prefix}{target['id']}-evidence-sheet.png",
            dpi=130,
        )
        plt.close(fig)
    (ROOT / "artifacts/reports" / packet_name).write_text(
        json.dumps(packets, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"Prepared {len(packets)} source-linked candidate packets; screening unchanged"
    )


if __name__ == "__main__":
    prepare()
