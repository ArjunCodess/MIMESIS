"""Physical correctness and evidence boundaries for the public research workflow."""
import copy

import numpy as np
import pytest

from src.terrain import features
from src.local_surface_v11 import fit_local_surface, summarize_exterior
from src.triad_study import Packet, Protocol, FineObservation, freeze, select, evaluate


def study():
    protocol = Protocol(id='synthetic-check', mode='synthetic_workflow_check', calibration_passed=True,
                        prior_art_cleared=True, coarse_scales=(1, 1), fine_bounds=(5, 5),
                        maximum_diameter_ratio=2, heldout_earth_setting='heldout', pairings=[('moon', 'mars')])
    packets = []
    for name, body, setting in [('earth', 'earth', 'training'), ('control', 'earth', 'training'),
                                ('holdout', 'earth', 'heldout'), ('moon', 'moon', 'mare'), ('mars', 'mars', 'volcano')]:
        packets.append(Packet(id=name, body=body, setting=setting, ancestry_group=name,
                              role='candidate' if body == 'earth' else 'evaluation', process='volcanic', diameter_m=100,
                              rim=[(0, 0), (1, 0), (1, 1), (0, 0)], rim_crs='local metres', rim_source='synthetic',
                              exact_identity_verified=True, quality_verified=True, sector_coverage=[1]*12,
                              source_hashes=['synthetic'], independent_evidence=['synthetic'],
                              coarse=[2, 2] if name == 'control' else [0, 0]))
    return protocol, packets


def test_known_plane_recovers_physical_slope_and_rejects_large_voids():
    y, x = np.mgrid[:160, :160] * 500
    values = .1*x + .2*y + 200
    result = features(values, 500)
    assert result['slope_median_deg'] == pytest.approx(np.degrees(np.arctan(np.hypot(.1, .2))))
    assert result['residual_rms_m'] < 1e-8
    values[60:100, 60:100] = np.nan
    assert features(values, 500) is None


def test_local_surface_does_not_fill_missing_sectors():
    y, x = np.mgrid[-150:151, -150:151]
    valid = x <= 0
    terrain = .1*x + .2*y
    terrain[~valid] = 1e12
    fitted = fit_local_surface(terrain, valid, x, y, np.ones(x.shape, bool), 1, 10)
    assert not fitted.usable[~valid].any()
    result = summarize_exterior(fitted, x, y, (0, 0), 40)
    assert result['state'] == 'insufficient_valid_exterior'
    assert any(row['roughness_m'] is None for row in result['sectors'])


def test_incomplete_evidence_and_modified_locks_cannot_enter_validation():
    protocol, packets = study()
    blocked = freeze(protocol.model_copy(update={'calibration_passed': False}), packets)
    with pytest.raises(ValueError):
        select(blocked)
    locked = select(freeze(protocol, packets))
    changed = copy.deepcopy(locked)
    changed['nominations'][0]['joint'] = 'control'
    with pytest.raises(ValueError, match='unchanged selection'):
        evaluate(changed, [])
    wrong_source = FineObservation(id='moon', source_hash='replacement', sectors=[(0, 0)]*12, sector_coverage=[1]*12)
    with pytest.raises(ValueError, match='frozen source manifest'):
        evaluate(locked, [wrong_source])


def test_two_earth_matches_cannot_hide_a_failed_moon_mars_comparison():
    protocol, packets = study()
    locked = select(freeze(protocol, packets))
    values = {'earth': 4, 'control': 0, 'holdout': 4, 'moon': 0, 'mars': 8}
    observations = [FineObservation(id=name, source_hash='synthetic', sectors=[(value, 0)]*12,
                                    sector_coverage=[1]*12) for name, value in values.items()]
    result = evaluate(locked, observations)['outcomes'][0]
    assert result['state'] == 'physical_bounds_fail'
    assert result['comparisons'][0]['passes'] is False
    assert all(row['passes'] for row in result['comparisons'] if row['first'] == 'earth')


def test_setting_holdout_cannot_share_development_source_ancestry():
    protocol, packets = study()
    packets[2] = packets[2].model_copy(update={'ancestry_group': 'earth'})
    result = freeze(protocol, packets)
    assert result['state'] == 'not_ready'
    assert any('held-out Earth setting shares' in reason for reason in result['failures'])
