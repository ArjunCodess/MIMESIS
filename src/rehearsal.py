"""Controlled Earth rehearsal packets, external evidence gates, and response scoring.

Hashes establish file integrity, never authorship, genuine independence or blinding.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pyproj import CRS, Transformer

from .validation import boundary_f1


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Source(Record):
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class Asset(Source):
    source_identifier: str = Field(min_length=1)
    blind_audit: str = Field(min_length=10)


class Reference(Source):
    source_identifier: str = Field(min_length=1)
    author_id: str
    independence_attestation: str = Field(min_length=10)
    geological_method: str = Field(min_length=10)
    coverage_attestation: str = Field(min_length=10)
    registration_attestation: str = Field(min_length=10)
    blind_attestation: str = Field(min_length=10)
    positional_accuracy_m: float = Field(gt=0)
    map_scale_denominator: float = Field(gt=0)
    tolerance_justification: str = Field(min_length=10)


class Pair(Record):
    pair_id: str
    target_id: str
    nomination_id: str
    control_id: str
    eligibility_record: Source
    nomination_training: Asset
    control_training: Asset
    mars_assessment: Asset
    reference: Reference
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(gt=-85, lt=85)
    body: Literal["Mars"] = "Mars"
    radius_m: Literal[3396190] = 3396190
    exposure_attestation: str = Field(min_length=10)
    independence_attestation: str = Field(min_length=10)


class Participant(Record):
    participant_id: str
    qualification_attestation: str = Field(min_length=10)
    independence_attestation: str = Field(min_length=10)
    no_prior_exposure_attestation: str = Field(min_length=10)
    role: Literal["mapper"] = "mapper"


class Inputs(Record):
    pairs: list[Pair] = Field(default_factory=list)
    participants: list[Participant] = Field(default_factory=list)
    external_attestation_record: Source | None = None

    @model_validator(mode="after")
    def unique_units(self):
        for values in ([p.pair_id for p in self.pairs], [p.target_id for p in self.pairs],
                       [p.participant_id for p in self.participants],
                       [x for p in self.pairs for x in (p.nomination_id, p.control_id)]):
            if len(values) != len(set(values)):
                raise ValueError("Pair, target, Earth block and participant IDs cannot be reused")
        authors = {p.reference.author_id for p in self.pairs}
        if authors & {p.participant_id for p in self.participants}:
            raise ValueError("Reference authors cannot be assessment participants")
        return self


class Protocol(Record):
    id: str = "mimesis-rehearsal-v9"
    seed: int = 20261115
    participants_per_condition: int = Field(default=2, ge=1)
    training_seconds: int = Field(default=600, gt=0)
    assessment_seconds: int = Field(default=600, gt=0)
    tolerance_m: float = Field(default=100, gt=0)
    maximum_extent_m: float = Field(default=40000, gt=0, le=100000)
    transfer_record: str = "artifacts/reports/transfer_v9.json"
    inputs_record: str | None = None


class Contact(Record):
    body: Literal["Mars"]
    coordinates: list[tuple[float, float]] = Field(min_length=2, max_length=10000)
    coordinate_system: Literal["body_longitude_latitude_degrees"]

    @model_validator(mode="after")
    def bounds(self):
        if any(not -180 <= lon <= 180 or not -90 <= lat <= 90 for lon, lat in self.coordinates):
            raise ValueError("Coordinates must be Mars longitude/latitude degrees")
        return self


class Response(Record):
    trial_id: str
    participant_id: str
    packet_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    training_started_s: float = Field(ge=0)
    training_finished_s: float = Field(ge=0)
    assessment_started_s: float = Field(ge=0)
    assessment_finished_s: float = Field(ge=0)
    response_id: str = Field(min_length=1)
    session_attestation: str = Field(min_length=10)
    contact: Contact


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def read_source(root: Path, source: Source) -> Path:
    path = (root / source.path).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"Missing or out-of-workspace source: {source.path}")
    if hashlib.sha256(path.read_bytes()).hexdigest() != source.sha256:
        raise ValueError(f"Source hash mismatch: {source.path}")
    return path


def project_contact(contact: Contact, pair: Pair, maximum_extent_m: float):
    local = CRS.from_proj4(f"+proj=aeqd +lat_0={pair.latitude} +lon_0={pair.longitude} +R={pair.radius_m} +units=m")
    project = Transformer.from_crs(local.geodetic_crs, local, always_xy=True)
    points = np.asarray([project.transform(*point) for point in contact.coordinates])
    if not np.isfinite(points).all() or np.max(np.linalg.norm(points, axis=1)) > maximum_extent_m:
        raise ValueError("Contact falls outside declared Mars assessment extent")
    if np.linalg.norm(np.diff(points, axis=0), axis=1).sum() == 0:
        raise ValueError("Contact must have nonzero length")
    return points


def prepare_study(root: Path, protocol: Protocol, inputs: Inputs):
    """Return private allocation and public readiness; never infer people from records."""
    transfer_path = root / protocol.transfer_record
    transfer = json.loads(transfer_path.read_text(encoding="utf-8"))
    source = {"path": protocol.transfer_record, "sha256": hashlib.sha256(transfer_path.read_bytes()).hexdigest()}
    gates, eligible = [], []
    if inputs.external_attestation_record is not None:
        read_source(root, inputs.external_attestation_record)
    for pair in sorted(inputs.pairs, key=lambda p: p.pair_id):
        # The supplied eligibility record is an externally approved frozen pair decision,
        # not a way to relabel the existing unqualified V9 blocks.
        evidence = json.loads(read_source(root, pair.eligibility_record).read_text(encoding="utf-8"))
        expected = {"pair_id": pair.pair_id, "target_id": pair.target_id,
                    "nomination_id": pair.nomination_id, "control_id": pair.control_id,
                    "state": "qualified_frozen_pair", "outcomes_inspected": False}
        missing = [key for key, value in expected.items() if key not in evidence or evidence[key] != value]
        for gate in ("source_eligibility", "context_nonoverlap", "matching_frozen", "reference_separation", "target_unexposed", "source_ancestry_review"):
            if not evidence.get(gate):
                missing.append(gate)
        if evidence.get("transfer_source_sha256") != source["sha256"]:
            missing.append("transfer_source_sha256")
        if inputs.external_attestation_record is None:
            missing.append("external_attestation_record")
        for asset in (pair.nomination_training, pair.control_training, pair.mars_assessment):
            read_source(root, asset)
        reference = Contact.model_validate(json.loads(read_source(root, pair.reference).read_text(encoding="utf-8")))
        project_contact(reference, pair, protocol.maximum_extent_m)
        floor = max(pair.reference.positional_accuracy_m, pair.reference.map_scale_denominator * .0005)
        if protocol.tolerance_m < floor:
            missing.append("reference_accuracy_or_map_scale")
        gates.append({"pair_id": pair.pair_id, "target_id": pair.target_id, "state": "eligible_by_supplied_attestations" if not missing else "blocked", "missing": missing})
        if not missing:
            eligible.append(pair)
    needed = 2 * protocol.participants_per_condition
    rng = random.Random(protocol.seed)
    people = sorted(inputs.participants, key=lambda p: p.participant_id)
    rng.shuffle(people)
    rng.shuffle(eligible)
    trials = []
    for pair in eligible:
        if len(people) < needed:
            next(g for g in gates if g["pair_id"] == pair.pair_id)["missing"].append("unused_participants_for_both_conditions")
            next(g for g in gates if g["pair_id"] == pair.pair_id)["state"] = "blocked"
            continue
        conditions = ["nomination", "control"] * protocol.participants_per_condition
        rng.shuffle(conditions)
        for condition in conditions:
            participant = people.pop()
            trial_id = f"T-{rng.getrandbits(128):032x}"
            asset = pair.nomination_training if condition == "nomination" else pair.control_training
            packet = {"trial_id": trial_id, "participant_id": participant.participant_id,
                      "training_seconds": protocol.training_seconds, "assessment_seconds": protocol.assessment_seconds,
                      "training_asset": "earth-training" + Path(asset.path).suffix,
                      "assessment_asset": "mars-assessment" + Path(pair.mars_assessment.path).suffix,
                      "coordinate_system": "body_longitude_latitude_degrees", "body": "Mars",
                      "instructions": "Complete Earth floor-to-margin mapping practice first. The facilitator closes Earth material after the fixed training period, then releases Mars assessment. Trace the basin-floor to organized-margin contact using the same legend. Submit one contact and timing record. No feedback, source names, ranks, reference contacts or previous trials are available during assessment."}
            trials.append({"trial_id": trial_id, "participant_id": participant.participant_id,
                           "pair_id": pair.pair_id, "condition": condition, "packet": packet,
                           "packet_hash": digest(packet), "training_source": asset.model_dump(),
                           "assessment_source": pair.mars_assessment.model_dump()})
    study = {"protocol": protocol.model_dump(), "inputs": inputs.model_dump(), "sources": [source], "trials": trials}
    study["study_hash"] = digest(study)
    ledger = {"id": protocol.id, "status": "ready_by_external_attestation" if trials else "missing_data_abstention",
              "authorized_trials": len(trials), "authorized_target_pairs": len({t['pair_id'] for t in trials}),
              "transfer_complete_pairs": transfer["summary"]["complete_transfer_pairs"], "gates": gates,
              "sources": [source], "study_hash": study["study_hash"],
              "independent_inputs_remaining": [] if trials else ["Qualified frozen source-linked unused nomination/control pairs and unexposed Mars targets", "Anonymized Earth training and Mars assessment products with external leakage audits", "Independent geological contact references with coverage, registration, positional accuracy and blinding attestations", "Qualified unexposed participants, separate reference authors, and an external independence attestation record"],
              "allocation_policy": "Seeded balanced between-participant allocation within target; each person performs one Earth intervention then one Mars assessment. No cross-target participant or Earth-block reuse. Pair order is shuffled; there is no assessment crossover or repeated-target learning.",
              "analysis_policy": "Contact F1 is a prespecified delineation endpoint after controlled Earth practice. Average participants within each condition then contrast within target. Repeated participants are not independent targets. Province/source dependencies need external review. No automatic superiority, utility, geological equivalence or equivalence-from-nonsignificance claim.",
              "attestation_limit": "Software checks records and hashes. Participant identity, source independence, geology, true blinding, qualifications, actual timing and no outside access require external verification."}
    return study, ledger


def score_responses(root: Path, study: dict, raw_responses: list[dict]):
    """Strict batch import. Reject duplicate/reused sessions before calculating outcomes."""
    frozen = {k: v for k, v in study.items() if k != "study_hash"}
    if digest(frozen) != study["study_hash"]:
        raise ValueError("Study provenance hash mismatch")
    protocol = Protocol.model_validate(study["protocol"])
    inputs = Inputs.model_validate(study["inputs"])
    for source in study["sources"]:
        read_source(root, Source.model_validate(source))
    rebuilt, _ = prepare_study(root, protocol, inputs)
    if rebuilt["study_hash"] != study["study_hash"]:
        raise ValueError("Study no longer matches frozen allocation and sources")
    responses = [Response.model_validate(r) for r in raw_responses]
    for values in ([r.trial_id for r in responses], [r.response_id for r in responses], [r.participant_id for r in responses]):
        if len(values) != len(set(values)):
            raise ValueError("Duplicate or reused response, trial or participant")
    trials = {t["trial_id"]: t for t in study["trials"]}
    pairs = {p.pair_id: p for p in inputs.pairs}
    scores = []
    for response in responses:
        if response.trial_id not in trials:
            raise ValueError("Unknown trial")
        trial = trials[response.trial_id]
        if response.participant_id != trial["participant_id"] or response.packet_hash != trial["packet_hash"]:
            raise ValueError("Participant or packet provenance mismatch")
        training = response.training_finished_s - response.training_started_s
        assessment = response.assessment_finished_s - response.assessment_started_s
        if training != protocol.training_seconds or not 0 < assessment <= protocol.assessment_seconds or response.assessment_started_s < response.training_finished_s:
            raise ValueError("Training/assessment timing or stage separation violation")
        pair = pairs[trial["pair_id"]]
        reference = Contact.model_validate(json.loads(read_source(root, pair.reference).read_text(encoding="utf-8")))
        result = boundary_f1(project_contact(response.contact, pair, protocol.maximum_extent_m),
                             project_contact(reference, pair, protocol.maximum_extent_m), protocol.tolerance_m,
                             pair.reference.positional_accuracy_m, pair.reference.map_scale_denominator)
        scores.append({"trial_id": response.trial_id, "pair_id": pair.pair_id, "condition": trial["condition"], "response_hash": digest(response.model_dump()), **result})
    contrasts = []
    for pair_id in sorted({t["pair_id"] for t in study["trials"]}):
        groups = {c: [s["f1"] for s in scores if s["pair_id"] == pair_id and s["condition"] == c and s["f1"] is not None] for c in ("nomination", "control")}
        complete = all(len(v) == protocol.participants_per_condition for v in groups.values())
        contrasts.append({"pair_id": pair_id, "state": "complete_descriptive_target_contrast" if complete else "missing_response_abstention",
                          "difference": float(np.mean(groups["nomination"]) - np.mean(groups["control"])) if complete else None})
    return {"study_hash": study["study_hash"], "response_batch_hash": digest(raw_responses), "scores": scores,
            "target_contrasts": contrasts, "state": "descriptive_only" if contrasts and all(c["difference"] is not None for c in contrasts) else "missing_data_abstention",
            "independence": "External attestation only; participant replication does not increase target sample size",
            "superiority": "not_automatically_established", "equivalence": "not_established"}
