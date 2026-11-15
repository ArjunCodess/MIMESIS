"""Feature-scale v10 measurements. Inputs are metric, north-up terrain with owned QA masks."""
from dataclasses import dataclass
import numpy as np
from scipy.ndimage import minimum_filter, gaussian_filter

@dataclass(frozen=True)
class Feature:
    center_x: float
    center_y: float
    diameter_m: float

    def __post_init__(self):
        if not np.isfinite([self.center_x,self.center_y,self.diameter_m]).all() or self.diameter_m <= 0:
            raise ValueError('Feature coordinates must be finite and diameter positive')

def measure_exterior(elevation, valid, x, y, feature, pixel_m, support_m, minimum_valid=.95):
    """Measure the fixed exterior annulus; quality failures never become smooth terrain.

    x/y are same-shape projected metre coordinate arrays, y increases north.
    Smoothing and derivative support are eroded out of the source mask.
    Returned sectors are descriptive partitions, never independent replicates.
    """
    z=np.asarray(elevation,dtype=float); mask=np.asarray(valid,dtype=bool)
    if z.ndim != 2 or mask.shape != z.shape or x.shape != z.shape or y.shape != z.shape:
        raise ValueError('Terrain, mask and metric coordinates must have identical 2D shapes')
    if not 0 < pixel_m <= support_m or not 0 < minimum_valid <= 1:
        raise ValueError('Require positive pixel spacing, support >= pixel spacing, and valid fraction in (0,1]')
    mask=mask & np.isfinite(z)
    extent=2*feature.diameter_m
    if (feature.center_x-extent < np.min(x) or feature.center_x+extent > np.max(x)
            or feature.center_y-extent < np.min(y) or feature.center_y+extent > np.max(y)):
        return {'state':'source_does_not_cover_fixed_annulus','support_m':support_m}
    radius=np.hypot(x-feature.center_x,y-feature.center_y)
    annulus=(radius >= feature.diameter_m/2) & (radius <= 2*feature.diameter_m)
    expected=int(annulus.sum())
    if not expected:raise ValueError('Feature annulus does not intersect source grid')
    # Gaussian standard deviation is the explicitly declared smoothing support,
    # not a claim about sensor effective resolution.
    sigma=support_m/pixel_m
    radius=int(np.ceil(3*sigma))+1
    # A separable Gaussian has square support. Cross-shaped erosion leaves
    # diagonal nodata inside the smoothing kernel and biases retained terrain.
    usable=minimum_filter(mask,size=2*radius+1,mode='constant',cval=0)
    common=annulus & usable
    fraction=float(common.sum()/expected)
    if fraction < minimum_valid:
        return {'state':'insufficient_valid_exterior','valid_fraction':fraction,'expected_cells':expected,'measured_cells':int(common.sum()),'support_m':support_m}
    smooth=gaussian_filter(np.where(mask,z,0),sigma=sigma,truncate=3)
    dy,dx=np.gradient(smooth,pixel_m)
    slopes=np.degrees(np.arctan(np.hypot(dx,dy)))
    design=np.column_stack([np.ones(common.sum()),x[common],y[common]])
    plane=np.linalg.lstsq(design,smooth[common],rcond=None)[0]
    residual=smooth-(plane[0]+plane[1]*x+plane[2]*y)
    angles=(np.degrees(np.arctan2(x-feature.center_x,y-feature.center_y))+360)%360
    sectors=[]
    for k in range(12):
        region=annulus & (angles >= k*30) & (angles < (k+1)*30)
        cells=region & usable
        f=float(cells.sum()/region.sum()) if region.any() else 0.
        sectors.append({'sector':k,'valid_fraction':f,'median_slope_deg':float(np.median(slopes[cells])) if cells.any() and f>=minimum_valid else None,'detrended_roughness_m':float(np.std(residual[cells])) if cells.any() and f>=minimum_valid else None})
    return {'state':'measured' if all(s['median_slope_deg'] is not None for s in sectors) else 'incomplete_sectors','support_m':support_m,'valid_fraction':fraction,'sectors':sectors,'independent_replicates':None}

def require_frozen_selection(selection, protocol_hash):
    if selection.get('protocol_hash') != protocol_hash or selection.get('state') != 'locked_before_validation':
        raise ValueError('Withheld outcomes require a matching locked protocol and selection')
    if not selection.get('nominations'):
        raise ValueError('No frozen nominations; validation cannot run')
