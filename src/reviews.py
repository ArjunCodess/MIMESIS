"""Validate imported reviewer judgments without inventing independence or agreement."""

from collections import Counter
from pydantic import BaseModel, Field
from typing import Literal


class Observation(BaseModel):
    status: Literal["supported", "contradicted", "unassessable"]
    reason: str = Field(min_length=10)


class PanelJudgment(BaseModel):
    panel_id: str
    basin_floor: Observation
    ridge_margin: Observation
    relief_transition: Observation


class ReviewSubmission(BaseModel):
    panel_set_hash: str = Field(min_length=64, max_length=64)
    reviewer_name: str = Field(min_length=2)
    qualifications: str = Field(min_length=10)
    independence_statement: str = Field(min_length=10)
    judgments: list[PanelJudgment] = Field(min_length=1, max_length=36)


def agreement(reviews: list[ReviewSubmission]):
    grouped = {}
    for review in reviews:
        for panel in review.judgments:
            for requirement in ("basin_floor", "ridge_margin", "relief_transition"):
                grouped.setdefault((panel.panel_id, requirement), []).append(
                    getattr(panel, requirement).status
                )
    comparable = [values for values in grouped.values() if len(values) > 1]
    return {
        "submitted_reviews": len(reviews),
        "comparable_requirement_rows": len(comparable),
        "exact_agreement_fraction": sum(
            len(Counter(values)) == 1 for values in comparable
        )
        / len(comparable)
        if comparable
        else None,
        "qualification_verification": "not_authenticated_by_software",
        "interpretation": "Agreement is descriptive; self-reported independence and duplicate identities need manual verification",
    }
