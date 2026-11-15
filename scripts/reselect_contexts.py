"""Correct frozen selection from unchanged, archived v2 measured features."""

from pathlib import Path
import json
from src.ranking import rank, canonical_hash
from src.selection import freeze_shortlist
from build_research import load_protocol

ROOT = Path(__file__).resolve().parents[1]
public = ROOT / "apps/web/public/research"
b = json.loads((ROOT / "artifacts/archive/expansion-v2/bundle.json").read_text())
protocol, expansion = load_protocol(True)
b["protocol"] = protocol
b["protocol_hash"] = canonical_hash(protocol)
b["experiment"] = {
    "version": "v3",
    "status": expansion["status"],
    "parent_archive": "artifacts/archive/expansion-v2",
}
frozen = {"protocol": protocol, "protocol_hash": b["protocol_hash"]}
(ROOT / "artifacts/reports/frozen_protocol.json").write_text(
    json.dumps(frozen, indent=2) + "\n", encoding="utf-8"
)
investigations = {}
for target in b["targets"]:
    for support, key in [(500, "rankings"), (1000, "rankings_1000")]:
        b[key][target["id"]] = rank(b["candidates"], target, protocol, support)
    result = b["rankings"][target["id"]]
    selected, roles, matches, unfilled = freeze_shortlist(
        result["candidates"],
        b["candidates"],
        expansion["selection_rule"],
        protocol["scenario_seed"],
    )
    dossiers = []
    for cid in selected:
        dossiers.append(
            {
                "candidate_id": cid,
                "role": roles[cid],
                "matched_to": matches.get(cid),
                "claim_level": "screened_candidate",
                "novelty_status": "unresolved",
                "reviewer_status": "not_reviewed",
                "corroboration": [],
                "field_tests": [
                    "Field slope transects to test DEM-scale relief",
                    "Surface descriptions and grain sizes to test substrate assumptions",
                    "Independent review of camera observations and site permissions",
                ],
            }
        )
    investigations[target["id"]] = {
        "id": target["id"],
        "run_hash": result["run_hash"],
        "shortlist": dossiers,
        "planned_count": 6,
        "actual_count": len(dossiers),
        "unfilled_slots": unfilled,
        "selection_rule": expansion["selection_rule"],
        "scope_note": "80 km contexts cannot overlap; unmatched slots are explicit",
        "claim": "Screened regional hypotheses; no discovery established",
    }
    print(
        target["id"],
        len(selected),
        "retained;",
        len(unfilled),
        "unfilled",
        [(roles[cid], cid) for cid in selected],
    )
b["investigations"] = investigations
(public / "bundle.json").write_text(json.dumps(b, indent=2) + "\n", encoding="utf-8")
(ROOT / "artifacts/reports/investigations.json").write_text(
    json.dumps(investigations, indent=2) + "\n", encoding="utf-8"
)
