"""Run bounded calibration controls and sensitivities, retaining every failure."""
from pathlib import Path
import hashlib
import json
import numpy as np
import rasterio
from rasterio.windows import from_bounds
from src.feature_v10 import Feature, measure_exterior

ROOT = Path(__file__).resolve().parents[1]
config_path = ROOT / 'configs/pit_calibration_audit_v10.json'
config = json.loads(config_path.read_text())
output = ROOT / 'artifacts/reports/discovery_v10'
cases = []
controls = []
for case in config['cases']:
    source_record = json.loads((ROOT / case['source_record']).read_text())
    for key, hash_key in [('terrain','terrain_sha256'),('confidence','confidence_sha256')]:
        actual = hashlib.file_digest((ROOT / case[key]).open('rb'),'sha256').hexdigest()
        if actual != source_record[hash_key]:
            raise ValueError(f'Source changed after inspection: {case[key]}')
    with rasterio.open(ROOT / case['terrain']) as terrain, rasterio.open(ROOT / case['confidence']) as confidence:
        cx,cy = source_record['source_grid_center_m']
        window = from_bounds(cx-600,cy-600,cx+600,cy+600,terrain.transform).round_offsets().round_lengths()
        z = terrain.read(1,window=window,masked=True)
        classes = confidence.read(1,window=window)
        affine = terrain.window_transform(window)
        row,col = np.indices(z.shape)
        # Use local metric coordinates for numerical conditioning of plane fits.
        x = affine.c+(col+.5)*affine.a-cx
        y = affine.f+(row+.5)*affine.e-cy
        flat = 100+.1*x+.2*y
        expected_slope = float(np.degrees(np.arctan(np.hypot(.1,.2))))
        runs = []
        for include_edited in [False,True]:
            quality = np.isin(classes,config['primary_quality_classes']+(config['edited_quality_sensitivity'] if include_edited else []))
            valid = quality & ~np.ma.getmaskarray(z) & np.isfinite(z.data)
            for diameter in case['funnel_diameters_m']:
                for offset in config['center_offsets_m']:
                    feature = Feature(*offset,diameter)
                    for support in config['supports_m']:
                        result = measure_exterior(z.data,valid,x,y,feature,terrain.res[0],support,config['minimum_valid_fraction'])
                        runs.append({'diameter_m':diameter,'center_offset_m':offset,'include_edited':include_edited,**result})
            # These controls test the algorithm independently of unknown geology.
            if not include_edited:
                for support in config['supports_m']:
                    feature = Feature(0,0,max(case['funnel_diameters_m']))
                    complete = measure_exterior(flat,np.ones(z.shape,bool),x,y,feature,terrain.res[0],support)
                    masked = measure_exterior(flat,valid,x,y,feature,terrain.res[0],support)
                    if complete['state'] != 'measured':
                        raise AssertionError('Complete analytical control was not measurable')
                    slope_error = max(abs(s['median_slope_deg']-expected_slope) for s in complete['sectors'])
                    roughness = max(s['detrended_roughness_m'] for s in complete['sectors'])
                    if slope_error > 1e-8 or roughness > 1e-8:
                        raise AssertionError('Analytical control did not recover the known plane')
                    controls.append({'case':case['id'],'support_m':support,'expected_slope_deg':expected_slope,'maximum_slope_error_deg':slope_error,'maximum_plane_residual_std_m':roughness,'complete_mask_state':complete['state'],'acquired_quality_mask_state':masked['state'],'acquired_mask_valid_fraction':masked.get('valid_fraction')})
    passed = sum(run['state']=='measured' for run in runs)
    cases.append({'id':case['id'],'name':case['name'],'runs':runs,'number_of_sensitivity_runs':len(runs),'complete_measurements':passed,'site_count':1})
    print(case['name'],passed,'complete measurements out of',len(runs),'calibration sensitivities',flush=True)
report = {'protocol':config_path.relative_to(ROOT).as_posix(),'protocol_sha256':hashlib.file_digest(config_path.open('rb'),'sha256').hexdigest(),
          'phase':'calibration; all cases already exposed','cases':cases,'analytical_controls':controls,
          'total_sensitivity_runs':sum(len(c['runs']) for c in cases),'lunar_calibration_sites':len(cases),
          'decision':'stop_current_pilot_before_selection' if not any(c['complete_measurements'] for c in cases) else 'further_source_and_geometry_qualification_required',
          'claim':'Case-level source-support results. Sensitivities and synthetic controls do not supply geological validation or population inference.'}
(output/'calibration_audit_v10.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
