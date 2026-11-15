"""Local plane estimates at observed terrain centers, using only qualified observations."""
from dataclasses import dataclass
import numpy as np
from scipy.ndimage import gaussian_filter


@dataclass(frozen=True)
class LocalSurface:
    slope_deg: np.ndarray
    roughness_m: np.ndarray
    usable: np.ndarray
    observed_weight_fraction: np.ndarray
    condition_number: np.ndarray


def fit_local_surface(z, valid, x, y, geometry_support, pixel_m, sigma_m,
                      minimum_weight_fraction=.8, maximum_condition=20):
    """Fit a Gaussian-weighted plane at observed centers, without filling rejected cells.

    The native center must be observed. Neighbor observations enter a least-squares
    model; invalid heights never enter it. Weight and geometry conditioning are
    reported separately from scored-footprint coverage, whose 95% rule is external.
    This changes the failed v10 estimator and must be calibrated before selection.
    """
    z=np.asarray(z,dtype=float);valid=np.asarray(valid,dtype=bool)
    geometry_support=np.asarray(geometry_support,dtype=bool)
    if z.ndim!=2 or any(a.shape!=z.shape for a in [valid,x,y,geometry_support]):
        raise ValueError('Terrain, coordinates and owned masks must share a two-dimensional grid')
    if not 0<pixel_m<=sigma_m or not 0<minimum_weight_fraction<=1 or maximum_condition<=1:
        raise ValueError('Invalid physical support or local-fit acceptance rule')
    sigma=sigma_m/pixel_m
    weights=valid&geometry_support&np.isfinite(z)
    expected=gaussian_filter(geometry_support.astype(float),sigma=sigma,truncate=3,mode='constant',cval=0)
    w=gaussian_filter(weights.astype(float),sigma=sigma,truncate=3,mode='constant',cval=0)
    fraction=np.divide(w,expected,out=np.zeros_like(w),where=expected>0)
    # Local crop coordinates avoid loss of precision from planetary eastings.
    xx=np.asarray(x,dtype=float)-float(np.mean(x)); yy=np.asarray(y,dtype=float)-float(np.mean(y))
    zz=np.where(weights,z,0)
    moments=[]
    for field in [xx,yy,zz,xx*xx,xx*yy,yy*yy,xx*zz,yy*zz,zz*zz]:
        total=gaussian_filter(np.where(weights,field,0),sigma=sigma,truncate=3,mode='constant',cval=0)
        moments.append(np.divide(total,w,out=np.zeros_like(total),where=w>0))
    mx,my,mz,mxx,mxy,myy,mxz,myz,mzz=moments
    vx=np.maximum(mxx-mx*mx,0);vy=np.maximum(myy-my*my,0);cov=mxy-mx*my
    xz=mxz-mx*mz;yz=myz-my*mz
    determinant=vx*vy-cov*cov
    discriminant=np.sqrt(np.maximum((vx-vy)**2+4*cov*cov,0))
    largest=(vx+vy+discriminant)/2;smallest=(vx+vy-discriminant)/2
    condition=np.divide(largest,smallest,out=np.full_like(w,np.inf),where=smallest>0)
    usable=weights&(fraction>=minimum_weight_fraction)&(condition<=maximum_condition)&(determinant>0)
    # Truncation at the array edge is not additional observational support.
    edge=int(np.ceil(3*sigma))+1
    if 2*edge>=min(z.shape):usable[:]=False
    else:
        usable[:edge,:]=False;usable[-edge:,:]=False;usable[:,:edge]=False;usable[:,-edge:]=False
    b=np.divide(xz*vy-yz*cov,determinant,out=np.zeros_like(w),where=usable)
    c=np.divide(yz*vx-xz*cov,determinant,out=np.zeros_like(w),where=usable)
    residual_variance=np.maximum(mzz-mz*mz-b*xz-c*yz,0)
    slopes=np.full_like(w,np.nan);roughness=np.full_like(w,np.nan)
    slopes[usable]=np.degrees(np.arctan(np.hypot(b[usable],c[usable])))
    roughness[usable]=np.sqrt(residual_variance[usable])
    return LocalSurface(slopes,roughness,usable,fraction,condition)


def summarize_exterior(surface, x, y, center, diameter_m, minimum_valid=.95):
    """Keep all fixed sectors in the result; missing ones cannot become zeros."""
    cx,cy=center;radius=np.hypot(x-cx,y-cy)
    footprint=(radius>=diameter_m/2)&(radius<=2*diameter_m)
    if not footprint.any():raise ValueError('No fixed exterior footprint on source grid')
    angle=(np.degrees(np.arctan2(x-cx,y-cy))+360)%360
    rows=[]
    for k in range(12):
        region=footprint&(angle>=30*k)&(angle<30*(k+1));expected=int(region.sum())
        use=region&surface.usable;fraction=float(use.sum()/expected) if expected else 0
        accepted=fraction>=minimum_valid
        rows.append({'sector':k,'expected_cells':expected,'usable_cells':int(use.sum()),'valid_fraction':fraction,
                     'slope_deg':float(np.median(surface.slope_deg[use])) if accepted else None,
                     'roughness_m':float(np.median(surface.roughness_m[use])) if accepted else None})
    return {'state':'measured' if all(row['slope_deg'] is not None for row in rows) else 'insufficient_valid_exterior',
            'valid_fraction':float(surface.usable[footprint].mean()),'sectors':rows,
            'minimum_scored_coverage':minimum_valid,'sector_interpretation':'Descriptive partitions of one feature'}
