"""Prepare anonymized panels and an empty expert-review form, without contacting anyone."""

import json
from pathlib import Path
import random
import shutil
from src.ranking import canonical_hash

ROOT = Path(__file__).resolve().parents[1]


def prepare():
    packets = json.loads(
        (ROOT / "artifacts/reports/discovery_evidence_packets.json").read_text()
    )
    random.Random(20261114).shuffle(packets)
    folder = ROOT / "artifacts/review"
    folder.mkdir(parents=True, exist_ok=True)
    panels, key = [], []
    for index, packet in enumerate(packets, 1):
        identifier = f"PANEL-{index:02d}"
        earth_name = identifier + "-earth.png"
        shutil.copy2(
            ROOT / "apps/web/public/research" / packet["earth_image"],
            folder / earth_name,
        )
        target_name = None
        if packet["planetary_image"]:
            target_name = identifier + "-target.png"
            shutil.copy2(
                ROOT / "apps/web/public/research" / packet["planetary_image"],
                folder / target_name,
            )
        panels.append(
            {
                "panel_id": identifier,
                "target_id": packet["target_id"],
                "earth_image": earth_name,
                "target_image": target_name,
                "earth_local_clear_fraction": packet["earth_local_clear_fraction"],
                "earth_context_clear_fraction": packet["earth_context_clear_fraction"],
                "planetary_valid_fraction": packet["planetary_valid_fraction"],
                "requirements": {
                    r: {"status": None, "reason": ""}
                    for r in ["basin_floor", "ridge_margin", "relief_transition"]
                },
            }
        )
        key.append(
            {
                "panel_id": identifier,
                "candidate_id": packet["candidate_id"],
                "role": packet["role"],
            }
        )
    form = {
        "status": "empty_not_a_review",
        "protocol": "Evaluate only visible floor, organized margin and resolved transition, with .95 coverage in both contexts. Mark unsupported observations contradicted and missing or ambiguous evidence unassessable. No rank preference or shared composition is inferred.",
        "reviewer": {"name": "", "qualifications": "", "independence_statement": ""},
        "panels": panels,
        "presentation": "Seeded random order, algorithm rank and shortlist role omitted; prior access to the public record can compromise blinding",
    }
    form["panel_set_hash"] = canonical_hash(panels)
    (folder / "review_form.json").write_text(
        json.dumps(form, indent=2), encoding="utf-8"
    )
    # The identity key is deliberately outside the reviewer package.
    (ROOT / "artifacts/reports/review_identity_key.json").write_text(
        json.dumps(key, indent=2), encoding="utf-8"
    )
    (folder / "README.md").write_text(
        "# MIMESIS review packet\n\nThis packet contains 36 randomly ordered source-linked comparisons and an empty form. No independent review has occurred. Keep the identity key separate. Submit completed observations for verification; a filled form does not by itself authenticate reviewer qualifications.\n",
        encoding="utf-8",
    )
    print(
        "Prepared 36 anonymized panels and an empty review form; no reviewer contacted"
    )


if __name__ == "__main__":
    prepare()
