"""Independent implementation of a published robust-scaled distance baseline.

Method reference: shishir-kuet/terrestrial-analog-finder. This adaptation uses
four MIMESIS scalar observables rather than upstream's six-feature contract.
It is a ranking diagnostic, not an eligibility or physical equivalence test.
"""
import numpy as np


def prepare(values):
    matrix = np.asarray(values, dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] != 4:
        raise ValueError('Expected relief, median slope, upper slope and roughness columns')
    observed = np.isfinite(matrix).all(axis=1) & (matrix[:, 0] >= 0) & (matrix[:, 3] >= 0)
    transformed = matrix.copy()
    transformed[:, [0, 3]] = np.log10(np.maximum(matrix[:, [0, 3]], 0) + 1)
    return transformed, observed


def fit_scales(reference):
    matrix, observed = prepare(reference)
    if observed.sum() < 2:
        raise ValueError('At least two complete reference observations are needed')
    finite = matrix[observed]
    scales = np.diff(np.percentile(finite, [25, 75], axis=0), axis=0)[0]
    scales = np.where(scales > 1e-12, scales, finite.std(axis=0))
    if np.any(scales <= 1e-12):
        raise ValueError('Reference population cannot scale a constant observable')
    return scales


def rank_baseline(values, target, scales):
    matrix, observed = prepare(values)
    target_matrix, target_valid = prepare([target])
    if not target_valid[0]:
        return np.full(len(matrix), np.nan)
    losses = np.full(len(matrix), np.nan)
    losses[observed] = np.sqrt(np.mean(((matrix[observed] - target_matrix[0]) / scales)**2, axis=1))
    return losses
