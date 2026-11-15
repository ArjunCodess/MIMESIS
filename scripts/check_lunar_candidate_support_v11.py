"""Confidence-only preflight of all other catalogue mare pits with listed DTMs."""
from pathlib import Path
import hashlib,json
import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.windows import from_bounds
from scipy.ndimage import minimum_filter

ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'data/metadata/discovery_v11/lunar-feature-inventory.json'
inventory=json.loads(source.read_text())
# The atlas DTM column is incomplete. Preserve it and add independently
# verified product-page links as source candidates, never as extra landforms.
supplemental=[]
for atlas_id, product in [(6,'NAC_DTM_INGENIIPIT'),(16,'NAC_DTM_FECUNPIT')]:
    entry=next(item for item in inventory if item['atlas_id']==atlas_id)
    supplemental.append({**entry,'fields':{**entry['fields'],'DTMs':product},
                         'supplemental_product_page':'https://data.lroc.im-ldi.com/lroc/view_rdr/'+product})
inventory=inventory+supplemental
rows=[]
for entry in inventory:
    f=entry.get('fields',{})
    if f.get('Terrain')!='Mare' or not f.get('DTMs','').startswith('NAC_DTM') or entry['atlas_id'] in [1,3]:continue
    product=f['DTMs'];folder=product.removeprefix('NAC_DTM_').lower()
    path=ROOT/'data/raw/discovery_v10'/('moon_'+folder)/(product+'_CONF.IMG')
    with rasterio.open(path) as d:
        counts=np.zeros(256,dtype=np.int64)
        for _,block in d.block_windows(1):
            counts+=np.bincount(d.read(1,window=block).ravel(),minlength=256)
        actual_values=np.flatnonzero(counts).tolist()
        documented_values={0,1,2,3,4,10,11,12,13,14,15}
        undocumented_values=sorted(set(actual_values)-documented_values)
        if undocumented_values:
            rows.append({'atlas_id':entry['atlas_id'],'name':f['Name'],'product':product,'native_posting_m':d.res[0],
                         'confidence_path':path.relative_to(ROOT).as_posix(),'confidence_sha256':hashlib.file_digest(path.open('rb'),'sha256').hexdigest(),
                         'observed_values':actual_values,'undocumented_values':undocumented_values,
                         'state':'unassessable_confidence_encoding','raw_quality_fraction':None,'gaussian_runs':[],
                         'interpretation':'Native PDS image values contradict the bundled class lookup. No valid-coverage result is computed.'})
            print(f['Name'],'UNASSESSABLE confidence encoding',len(undocumented_values),'undocumented codes',flush=True)
            continue
        cx,cy=Transformer.from_crs(d.crs.geodetic_crs,d.crs,always_xy=True,force_over=True).transform(float(f['Long.']),float(f['Lat.']))
        window=from_bounds(cx-1000,cy-1000,cx+1000,cy+1000,d.transform).round_offsets().round_lengths()
        a=d.read(1,window=window,boundless=True,fill_value=0);t=d.window_transform(window)
        row,col=np.indices(a.shape);x=t.c+(col+.5)*t.a-cx;y=t.f+(row+.5)*t.e-cy
        diameter=float(f['Funnel Max. Diam.']);r=np.hypot(x,y)
        region=(r>=diameter/2)&(r<=2*diameter);good=np.isin(a,[10,11,12,13,14])
        angles=(np.degrees(np.arctan2(x,y))+360)%360
        sector_native=[float(good[region&(angles>=k*30)&(angles<(k+1)*30)].mean()) for k in range(12)]
        runs=[]
        for sigma in [10,20,40]:
            radius=int(np.ceil(3*sigma/d.res[0]))+1
            usable=minimum_filter(good,size=2*radius+1,mode='constant',cval=0)
            runs.append({'sigma_m':sigma,'usable_fraction':float((usable&region).sum()/region.sum())})
        result={'atlas_id':entry['atlas_id'],'name':f['Name'],'product':product,'native_posting_m':d.res[0],
                'confidence_path':path.relative_to(ROOT).as_posix(),'confidence_sha256':hashlib.file_digest(path.open('rb'),'sha256').hexdigest(),
                'raw_quality_fraction':float(good[region].mean()),'native_sector_fractions':sector_native,'gaussian_runs':runs,
                'state':'confidence_only_preflight; terrain values and native finite mask not inspected',
                'group':product,'geometry':'Published maximum funnel diameter circle; exact rim not yet digitized'}
        rows.append(result);print(result['name'],result['native_posting_m'],result['raw_quality_fraction'],runs,flush=True)
out=ROOT/'artifacts/reports/discovery_v11';out.mkdir(parents=True,exist_ok=True)
(out/'lunar_candidate_source_support.json').write_text(json.dumps({'atlas_inventory_sha256':hashlib.file_digest(source.open('rb'),'sha256').hexdigest(),'supplemental_product_pages':[e['supplemental_product_page'] for e in supplemental],'cases':rows,'selection':'Every remaining mare entry with a listed DTM, plus independently verified Ingenii and Fecunditatis product pages. Alternative products of one feature are not independent cases. No outcome-based shortlist.','not_computed':['fine terrain descriptors','analogue scores','nominations','validation outcomes']},indent=2)+'\n')
