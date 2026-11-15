"""Apply explicit authored release decisions; rank alone never promotes a claim."""

from typing import Literal
from pydantic import BaseModel, Field


class ClaimReview(BaseModel):
    candidate_id: str
    target_id: str
    requested_level: Literal[
        "corroborated_candidate",
        "proposed_new_association",
        "new_characterization_of_known_analogue",
    ]
    novelty_decision: Literal[
        "known_analogue_context", "no_prior_located_bounded_search", "unresolved"
    ]
    source_urls: list[str] = Field(min_length=1)
    reviewed_at: str
    assessor: str
    rationale: str = Field(min_length=30)


def release_claim(dossier: dict, ranking_row: dict, review: ClaimReview | None):
    if review is None:
        return {
            "claim_level": "screened_candidate",
            "reason": "No authored claim review; numerical ranking does not promote a claim",
        }
    if review.candidate_id != dossier["candidate_id"]:
        raise ValueError(
            "Claim review and evidence dossier must identify the same footprint"
        )
    if not ranking_row["passes_provisional_threshold"]:
        return {
            "claim_level": "screened_candidate",
            "reason": "Frozen robust discrepancy gate is unmet",
        }
    if dossier["assessment_outcome"] != "provisional_visual_support":
        return {
            "claim_level": "unresolved",
            "reason": "Mandatory visible morphology or source coverage is incomplete or contradicted",
        }
    if (
        review.requested_level == "proposed_new_association"
        and review.novelty_decision != "no_prior_located_bounded_search"
    ):
        return {
            "claim_level": "corroborated_candidate",
            "reason": "Visible morphology is supported, but the authored novelty decision does not support a proposed new association",
        }
    if (
        review.requested_level == "new_characterization_of_known_analogue"
        and review.novelty_decision != "known_analogue_context"
    ):
        return {
            "claim_level": "corroborated_candidate",
            "reason": "Known-analogue characterization requires a source-linked prior association",
        }
    return {
        "claim_level": review.requested_level,
        "reason": review.rationale,
        "review": review.model_dump(),
        "limitation": "Model-assisted remote characterization; no independent expert or field validation. A bounded search cannot prove absence of prior work.",
    }
