"""Geographic comparisons for ranked, overlapping terrain windows."""
import numpy as np
from pyproj import Geod
from scipy.optimize import linear_sum_assignment

GEOD = Geod(ellps='WGS84')


def center_distance_km(first, second):
    return GEOD.inv(first['longitude'], first['latitude'], second['longitude'], second['latitude'])[2] / 1000


def window_iou(first, second, width_m=20000):
    """Area overlap of equal squares in the same regional measurement projection."""
    if first['region_id'] != second['region_id']:
        return 0.0
    area = max(0, width_m - abs(first['easting_m'] - second['easting_m'])) * max(
        0, width_m - abs(first['northing_m'] - second['northing_m']))
    return area / (2 * width_m**2 - area)


def geographic_matches(first, second, radii_km):
    """Maximum one-to-one matches within each radius; no candidate counts twice."""
    distances = np.array([[center_distance_km(a, b) for b in second] for a in first])
    results = []
    for radius in radii_km:
        # The total secondary cost is < 1, so an extra valid pair always wins.
        cost = (distances > radius).astype(float) + distances / (distances.max() + 1) / min(distances.shape)
        rows, columns = linear_sum_assignment(cost)
        pairs = [(int(i), int(j)) for i, j in zip(rows, columns) if distances[i, j] <= radius]
        results.append({'radius_km': radius, 'matched_pairs': len(pairs),
                        'pairs': [{'first_id': first[i]['id'], 'second_id': second[j]['id'],
                                   'distance_km': float(distances[i, j])} for i, j in pairs]})
    return results
