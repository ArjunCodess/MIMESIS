"""Numerical calibration on known fields and observed quality masks, not geological validation."""
from pathlib import Path
import json
import numpy as np
import rasterio
from rasterio.windows import from_bounds
from pyproj import Transformer
from src.local_surface_v11 import fit_local_surface,summarize_exterior

ROOT=Path(__file__).resolve().parents[1];REPORT=ROOT/'artifacts/reports/discovery_v11'
REPORT.mkdir(parents=True,exist_ok=True)
inventory=json.loads((ROOT/'data/metadata/discovery_v11/lunar-feature-inventory.json').read_text())
cases=[]
for identifier in [1,3,10,11]:
    entry=next(r for r in inventory if r['atlas_id']==identifier);f=entry['fields'];product=f['DTMs']
    if identifier==1:folder='moon_marius'
    elif identifier==3:folder='moon_quality'
    else:folder='moon_'+product.removeprefix('NAC_DTM_').lower()
    path=ROOT/'data/raw/discovery_v10'/folder/(product+'_CONF.IMG')
    with rasterio.open(path) as d:
        cx,cy=Transformer.from_crs(d.crs.geodetic_crs,d.crs,always_xy=True,force_over=True).transform(float(f['Long.']),float(f['Lat.']))
        diameter=float(f['Funnel Max. Diam.']);half=2*diameter+150
        window=from_bounds(cx-half,cy-half,cx+half,cy+half,d.transform).round_offsets().round_lengths()
        q=d.read(1,window=window,boundless=True,fill_value=0);a=d.window_transform(window)
        row,col=np.indices(q.shape);x=a.c+(col+.5)*a.a-cx;y=a.f+(row+.5)*a.e-cy
        radius=np.hypot(x,y);outside=radius>=diameter/2;quality=np.isin(q,[10,11,12,13,14])
        runs=[]
        for sigma in [10,20,40]:
            plane=10+.1*x+.2*y
            for kind,z in [('plane',plane),('bumpy',plane+3*np.sin(x/4)*np.cos(y/4))]:
                full=fit_local_surface(z,outside,x,y,outside,d.res[0],sigma)
                masked=fit_local_surface(z,quality,x,y,outside,d.res[0],sigma)
                summary=summarize_exterior(masked,x,y,(0,0),diameter)
                region=(radius>=diameter/2)&(radius<=2*diameter)
                common=full.usable&masked.usable&region
                run={'sigma_m':sigma,'known_field':kind,'scored_footprint':summary,
                     'mask_vs_complete_operator_median_absolute_slope_difference_deg':float(np.median(np.abs(masked.slope_deg[common]-full.slope_deg[common]))) if common.any() else None,
                     'mask_vs_complete_operator_p95_absolute_slope_difference_deg':float(np.percentile(np.abs(masked.slope_deg[common]-full.slope_deg[common]),95)) if common.any() else None,
                     'mask_vs_complete_operator_p95_absolute_roughness_difference_m':float(np.percentile(np.abs(masked.roughness_m[common]-full.roughness_m[common]),95)) if common.any() else None}
                runs.append(run)
    cases.append({'atlas_id':identifier,'name':f['Name'],'runs':runs})
    print(f['Name'],[(r['known_field'],r['sigma_m'],r['scored_footprint']['state'],round(r['scored_footprint']['valid_fraction'],4),r['mask_vs_complete_operator_p95_absolute_roughness_difference_m']) for r in runs],flush=True)
(REPORT/'local_surface_calibration.json').write_text(json.dumps({'phase':'Numerical calibration and source-mask feasibility only','method':'Gaussian-weighted local plane at observed centers; 80% neighbor weight and condition<=20; 95% of every fixed scored sector still required','cases':cases,'limits':'Known analytical fields are synthetic controls, not terrain observations or geological validation. No real fine-terrain outcome or analogue score is computed.'},indent=2,allow_nan=False)+'\n')
