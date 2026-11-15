"""Calibration feasibility for native height pairs; no interpolation or nominations."""
from pathlib import Path
import json
import numpy as np
import rasterio
from rasterio.windows import from_bounds

ROOT=Path(__file__).resolve().parents[1]
config=json.loads((ROOT/'configs/pit_calibration_audit_v10.json').read_text())
cases=[]
for case in config['cases']:
    record=json.loads((ROOT/case['source_record']).read_text())
    with rasterio.open(ROOT/case['terrain']) as dtm,rasterio.open(ROOT/case['confidence']) as conf:
        cx,cy=record['source_grid_center_m']
        window=from_bounds(cx-1000,cy-1000,cx+1000,cy+1000,dtm.transform).round_offsets().round_lengths()
        z=dtm.read(1,window=window,masked=True);q=conf.read(1,window=window)
        transform=dtm.window_transform(window);row,col=np.indices(z.shape)
        x=transform.c+(col+.5)*transform.a-cx;y=transform.f+(row+.5)*transform.e-cy
        radius=np.hypot(x,y);d=record['proxy_diameter_m']
        good=~np.ma.getmaskarray(z)&np.isin(q,[10,11,12,13,14])
        angle=(np.degrees(np.arctan2(x,y))+360)%360
        runs=[]
        for inner,outer in [(.5,2),(1,2),(1,3),(1.5,3),(2,4)]:
          region=(radius>=inner*d)&(radius<=outer*d)
          for lag in [12,20,40]:
            shift=int(round(lag/dtm.res[0]));directions=[]
            for axis in [0,1]:
                far_region=np.roll(region,-shift,axis=axis);far_good=np.roll(good,-shift,axis=axis)
                expected=region&far_region
                valid=expected&good&far_good
                sectors=[]
                for k in range(12):
                    sector=(angle>=k*30)&(angle<(k+1)*30)
                    n=int((expected&sector).sum());v=int((valid&sector).sum())
                    sectors.append(v/n if n else None)
                directions.append({'axis':axis,'expected_pairs':int(expected.sum()),'valid_pairs':int(valid.sum()),'valid_fraction':float(valid.sum()/expected.sum()),'sector_valid_fractions':sectors})
            runs.append({'annulus_diameters':[inner,outer],'lag_requested_m':lag,'lag_actual_m':shift*dtm.res[0],'directions':directions})
    cases.append({'site':case['id'],'runs':runs})
    print(case['id'],[(r['annulus_diameters'],r['lag_requested_m'],[round(v['valid_fraction'],4) for v in r['directions']],[round(min(v['sector_valid_fractions']),4) for v in r['directions']]) for r in runs],flush=True)
(ROOT/'artifacts/reports/discovery_v10/native_pair_support_probe.json').write_text(json.dumps({'phase':'calibration feasibility only','cases':cases,'limits':'Operator and footprint differ from Gaussian protocol; this probe does not supersede that failed result or qualify a new protocol.'},indent=2)+'\n')
