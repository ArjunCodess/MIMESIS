"""Frozen feature-level selection and withheld evaluation.

Source eligibility is an input backed by evidence, never inferred from a good
score. The module owns JSON boundary validation; internal functions use typed
records. Synthetic fixtures exercise the workflow without creating discoveries.
"""
import hashlib
import json
import math
import random
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator
from shapely.geometry import Polygon


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class Packet(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    id: str
    body: Literal['earth', 'moon', 'mars']
    setting: str
    ancestry_group: str
    role: Literal['candidate', 'calibration', 'evaluation', 'hard_negative']
    process: str
    diameter_m: FiniteFloat = Field(gt=0)
    rim: list[tuple[FiniteFloat, FiniteFloat]] = Field(min_length=4)
    rim_crs: str = Field(min_length=1)
    rim_source: str = Field(min_length=1)
    exact_identity_verified: bool
    quality_verified: bool
    sector_coverage: list[FiniteFloat] = Field(min_length=12, max_length=12)
    source_hashes: list[str] = Field(min_length=1)
    independent_evidence: list[str]
    coarse: list[FiniteFloat] = Field(min_length=2, max_length=2, description='Coarse median slope in degrees, then coarse relief in metres')

    @model_validator(mode='after')
    def geometry_and_coverage(self):
        if self.rim[0] != self.rim[-1]:
            raise ValueError('Feature rim must be closed')
        polygon = Polygon(self.rim)
        if not polygon.is_valid or polygon.area <= 0:
            raise ValueError('Feature rim must enclose a valid polygon')
        if any(value < 0 or value > 1 for value in self.sector_coverage):
            raise ValueError('Sector coverage must be a fraction')
        return self


class ChallengeSpec(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    name: str
    kind: Literal['coarser_support', 'lookalike', 'mask', 'repeated_acquisition', 'registration', 'height']
    evidence: str = Field(min_length=1)
    parameters: dict[str, FiniteFloat | str]


class Protocol(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    id: str
    mode: Literal['confirmatory', 'synthetic_workflow_check'] = 'confirmatory'
    calibration_passed: bool = False
    prior_art_cleared: bool = False
    coarse_scales: tuple[FiniteFloat, FiniteFloat] = Field(description='Slope degrees and relief metres; fixed during calibration')
    fine_bounds: tuple[FiniteFloat, FiniteFloat] = Field(description='Maximum sector-pattern RMS differences: slope degrees and roughness metres')
    maximum_diameter_ratio: FiniteFloat = Field(ge=1)
    heldout_earth_setting: str
    seed: int = 2026
    pairings: list[tuple[str, str]] = Field(min_length=1)
    challenges: list[ChallengeSpec] = Field(default_factory=list)

    @model_validator(mode='after')
    def positive_scales(self):
        if min(*self.coarse_scales, *self.fine_bounds) <= 0:
            raise ValueError('Comparison scales and physical bounds must be positive')
        return self


def freeze(protocol: Protocol, packets: list[Packet]):
    failures = []
    ids = [packet.id for packet in packets]
    if len(ids) != len(set(ids)):
        failures.append('duplicate feature identity')
    if not protocol.calibration_passed:
        failures.append('positive/negative calibration is incomplete')
    if not protocol.prior_art_cleared:
        failures.append('prior-art gate is unresolved')
    for packet in packets:
        if not packet.exact_identity_verified or not packet.quality_verified or min(packet.sector_coverage) < .95:
            failures.append(packet.id + ': identity or fixed-sector quality is insufficient')
        if not packet.independent_evidence:
            failures.append(packet.id + ': no independent evidence')
    earth = [packet for packet in packets if packet.body == 'earth' and packet.role == 'candidate']
    if not any(packet.setting == protocol.heldout_earth_setting for packet in earth):
        failures.append('held-out Earth setting is absent')
    development_groups = {packet.ancestry_group for packet in earth if packet.setting != protocol.heldout_earth_setting}
    heldout_groups = {packet.ancestry_group for packet in earth if packet.setting == protocol.heldout_earth_setting}
    if development_groups & heldout_groups:
        failures.append('held-out Earth setting shares source ancestry with development settings')
    roles_by_group = {}
    for packet in packets:
        roles_by_group.setdefault((packet.body, packet.ancestry_group), set()).add(packet.role)
    if any('calibration' in roles and 'evaluation' in roles for roles in roles_by_group.values()):
        failures.append('calibration and evaluation share a source-ancestry group')
    if protocol.mode == 'confirmatory':
        required_challenges = {'coarser_support', 'lookalike', 'mask', 'repeated_acquisition', 'registration', 'height'}
        if not required_challenges.issubset({item.kind for item in protocol.challenges}):
            failures.append('source-backed perturbation and challenge specifications are incomplete')
        if len(earth) < 12 or len({packet.setting for packet in earth}) < 4:
            failures.append('proposed twelve-feature, four-setting Earth bank is incomplete')
        for body in ['moon', 'mars']:
            for role, minimum in [('calibration', 2), ('evaluation', 4)]:
                groups = {packet.ancestry_group for packet in packets if packet.body == body and packet.role == role}
                if len(groups) < minimum:
                    failures.append(f'{body}: fewer than {minimum} independent {role} groups')
    lookup = {packet.id: packet for packet in packets}
    for moon_id, mars_id in protocol.pairings:
        if moon_id not in lookup or mars_id not in lookup:
            failures.append('pairing references an absent feature')
        elif lookup[moon_id].body != 'moon' or lookup[mars_id].body != 'mars' or any(lookup[key].role != 'evaluation' for key in [moon_id, mars_id]):
            failures.append('pairing must use lunar and Martian evaluation features')
    document = {'protocol': protocol.model_dump(mode='json'), 'packets': [packet.model_dump(mode='json') for packet in packets]}
    return {**document, 'hash': digest(document), 'state': 'eligible_for_selection' if not failures else 'not_ready',
            'failures': failures}


def select(frozen):
    if frozen['state'] != 'eligible_for_selection' or digest({key: frozen[key] for key in ['protocol', 'packets']}) != frozen['hash']:
        raise ValueError('Selection requires a verified eligible freeze')
    protocol = Protocol.model_validate(frozen['protocol'])
    packets = [Packet.model_validate(value) for value in frozen['packets']]
    lookup = {packet.id: packet for packet in packets}
    training = [packet for packet in packets if packet.body == 'earth' and packet.role == 'candidate' and packet.setting != protocol.heldout_earth_setting]
    heldout = [packet for packet in packets if packet.body == 'earth' and packet.role == 'candidate' and packet.setting == protocol.heldout_earth_setting]
    nominations = []
    for split, earth in [('development_settings', training), ('heldout_setting', heldout)]:
        for moon_id, mars_id in protocol.pairings:
            moon, mars = lookup[moon_id], lookup[mars_id]
            eligible = [packet for packet in earth if max(packet.diameter_m, moon.diameter_m, mars.diameter_m) /
                        min(packet.diameter_m, moon.diameter_m, mars.diameter_m) <= protocol.maximum_diameter_ratio]
            if not eligible:
                nominations.append({'split': split, 'moon': moon_id, 'mars': mars_id, 'state': 'no_size_compatible_candidate'})
                continue
            distance = lambda a, b: float(np.sqrt(np.mean(((np.asarray(a.coarse)-b.coarse)/protocol.coarse_scales)**2)))
            joint = min(eligible, key=lambda packet: (max(distance(packet, moon), distance(packet, mars)), packet.id))
            separate = {body: min(eligible, key=lambda packet: (distance(packet, target), packet.id)).id
                        for body, target in [('moon', moon), ('mars', mars)]}
            alternatives = [packet for packet in eligible if packet.id != joint.id and packet.process == moon.process == mars.process]
            matched = min(alternatives, key=lambda packet: (max(abs(math.log(packet.diameter_m/target.diameter_m)) for target in [moon, mars]), packet.id)).id if alternatives else None
            # Stable population and per-pair seed make replay independent of input order.
            seed = int(digest([protocol.seed, split, moon_id, mars_id])[:16], 16)
            seeded = random.Random(seed).choice(sorted(eligible, key=lambda packet: packet.id)).id
            nominations.append({'split': split, 'moon': moon_id, 'mars': mars_id, 'state': 'locked',
                                'joint': joint.id, 'separate': separate, 'baselines': {'nearest_coarse': separate, 'process_size_matched': matched, 'seeded': seeded},
                                'hard_negatives': sorted(packet.id for packet in packets if packet.body == 'earth' and packet.role == 'hard_negative'
                                                         and max(packet.diameter_m, moon.diameter_m, mars.diameter_m) / min(packet.diameter_m, moon.diameter_m, mars.diameter_m) <= protocol.maximum_diameter_ratio),
                                'eligible_population': sorted(packet.id for packet in eligible)})
    document = {'freeze_hash': frozen['hash'], 'protocol': protocol.model_dump(mode='json'), 'nominations': nominations,
                'allowed_sources': {packet.id: packet.source_hashes for packet in packets},
                'claim': 'Synthetic workflow check only' if protocol.mode == 'synthetic_workflow_check' else 'Locked before withheld observations'}
    return {**document, 'hash': digest(document), 'state': 'locked_before_validation'}


class FineObservation(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    id: str
    source_hash: str
    sectors: list[tuple[FiniteFloat, FiniteFloat]] = Field(min_length=12, max_length=12, description='Twelve fixed north-referenced sectors, each containing slope degrees and roughness metres')
    sector_coverage: list[FiniteFloat] = Field(min_length=12, max_length=12)

    @model_validator(mode='after')
    def coverage_is_fraction(self):
        if any(value < 0 or value > 1 for value in self.sector_coverage):
            raise ValueError('Withheld coverage must be a fraction')
        return self


def verify_selection(selection):
    content = {key: selection[key] for key in ['freeze_hash', 'protocol', 'nominations', 'allowed_sources', 'claim']}
    if selection['state'] != 'locked_before_validation' or digest(content) != selection['hash']:
        raise ValueError('Withheld evaluation requires an unchanged selection lock')
    return Protocol.model_validate(selection['protocol'])


def evaluate(selection, observations: list[FineObservation]):
    protocol = verify_selection(selection)
    lookup = {row.id: row for row in observations}
    if len(lookup) != len(observations):
        raise ValueError('Duplicate withheld feature identity')
    for row in observations:
        if row.id not in selection['allowed_sources'] or row.source_hash not in selection['allowed_sources'][row.id]:
            raise ValueError('Withheld observation source differs from the frozen source manifest')
    outcomes = []
    for nomination in selection['nominations']:
        if nomination['state'] != 'locked':
            outcomes.append(nomination)
            continue
        candidates = set([nomination['joint'], *nomination['separate'].values(), nomination['baselines']['seeded'], *nomination['hard_negatives']])
        if nomination['baselines']['process_size_matched']:
            candidates.add(nomination['baselines']['process_size_matched'])
        pair_ids = [(nomination['moon'], nomination['mars'])]
        pair_ids += [(candidate, target) for candidate in sorted(candidates) for target in [nomination['moon'], nomination['mars']]]
        comparisons = []
        for first, second in pair_ids:
            if first not in lookup or second not in lookup or min(*lookup[first].sector_coverage, *lookup[second].sector_coverage) < .95:
                comparisons.append({'first': first, 'second': second, 'state': 'unassessable', 'passes': None})
                continue
            delta = np.asarray(lookup[first].sectors) - np.asarray(lookup[second].sectors)
            rms = np.sqrt(np.mean(delta**2, axis=0))
            comparisons.append({'first': first, 'second': second, 'state': 'measured', 'rms_slope_deg': float(rms[0]),
                                'rms_roughness_m': float(rms[1]), 'passes': bool(np.all(rms <= protocol.fine_bounds))})
        joint_pairs = [row for row in comparisons if row['first'] == nomination['joint'] or (row['first'], row['second']) == (nomination['moon'], nomination['mars'])]
        result = 'unassessable' if any(row['passes'] is None for row in joint_pairs) else ('physical_bounds_pass' if all(row['passes'] for row in joint_pairs) else 'physical_bounds_fail')
        matched_id = nomination['baselines']['process_size_matched']
        baseline_effects = []
        for target in [nomination['moon'], nomination['mars']]:
            joint = next(row for row in comparisons if row['first'] == nomination['joint'] and row['second'] == target)
            alternative = next((row for row in comparisons if row['first'] == matched_id and row['second'] == target), None)
            available = alternative is not None and joint['state'] == alternative['state'] == 'measured'
            baseline_effects.append({'target': target, 'alternative': matched_id,
                                     'state': 'measured' if available else 'unassessable',
                                     'joint_minus_alternative_slope_deg': joint['rms_slope_deg']-alternative['rms_slope_deg'] if available else None,
                                     'joint_minus_alternative_roughness_m': joint['rms_roughness_m']-alternative['rms_roughness_m'] if available else None})
        outcomes.append({'nomination': nomination, 'state': result, 'comparisons': comparisons,
                         'process_matched_baseline_effects': baseline_effects})
    return {'selection_hash': selection['hash'], 'observation_hash': digest([row.model_dump(mode='json') for row in observations]),
            'mode': protocol.mode, 'outcomes': outcomes,
            'claim': 'Physical comparisons only; baseline advantage, perturbation challenges, corroboration and novelty remain separate requirements'}


def challenge(selection, scenarios: dict[str, list[FineObservation]]):
    protocol = verify_selection(selection)
    declared = {item.name: item for item in protocol.challenges}
    if len(declared) != len(protocol.challenges):
        raise ValueError('Challenge names must be unique')
    if set(scenarios) - set(declared):
        raise ValueError('Challenge observations must match a specification frozen before selection')
    outcomes = []
    for name, specification in declared.items():
        if name not in scenarios:
            outcomes.append({'name': name, 'state': 'not_run', 'reason': 'Qualified observations for the declared variant are absent'})
        else:
            outcomes.append({'name': name, 'specification': specification.model_dump(mode='json'),
                             'state': 'evaluated', 'result': evaluate(selection, scenarios[name])})
    return {'selection_hash': selection['hash'], 'challenges': outcomes,
            'claim': 'Sensitivity outcomes preserve the primary lock and full-sector denominator; they do not replace the primary test or establish novelty'}
