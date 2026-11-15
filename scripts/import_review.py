"""Validate an actually completed anonymous-panel form and retain its real provenance."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from src.reviews import ReviewSubmission, agreement
from src.ranking import canonical_hash

ROOT = Path(__file__).resolve().parents[1]


def ingest(path):
    value = json.loads(path.read_text())
    frozen = json.loads((ROOT / "artifacts/review/review_form.json").read_text())
    if value["panel_set_hash"] != frozen["panel_set_hash"]:
        raise ValueError("Review form does not match the frozen panel set")
    valid_ids = {p["panel_id"] for p in frozen["panels"]}
    submission = ReviewSubmission.model_validate(
        {
            "panel_set_hash": value["panel_set_hash"],
            "reviewer_name": value["reviewer"]["name"],
            "qualifications": value["reviewer"]["qualifications"],
            "independence_statement": value["reviewer"]["independence_statement"],
            "judgments": [
                {"panel_id": p["panel_id"], **p["requirements"]}
                for p in value["panels"]
            ],
        }
    )
    ids = [p.panel_id for p in submission.judgments]
    if len(set(ids)) != len(ids) or not set(ids) <= valid_ids:
        raise ValueError("Duplicate or unknown review panel")
    folder = ROOT / "artifacts/reviews"
    folder.mkdir(parents=True, exist_ok=True)
    record = submission.model_dump()
    identifier = canonical_hash(record)
    (folder / f"{identifier}.json").write_text(
        json.dumps(
            {
                "received_at": datetime.now(timezone.utc).isoformat(),
                "submission": record,
                "status": "submitted_qualifications_unverified",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    reviews = [
        ReviewSubmission.model_validate(json.loads(p.read_text())["submission"])
        for p in folder.glob("*.json")
    ]
    summary = agreement(reviews)
    (ROOT / "artifacts/reports/reviewer_agreement.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("form", type=Path)
    ingest(parser.parse_args().form)
