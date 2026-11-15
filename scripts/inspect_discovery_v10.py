"""Inspect native pilot rasters without assigning undocumented quality classes."""
from pathlib import Path
import hashlib,json
import numpy as np
import rasterio
ROOT=Path(__file__).resolve().parents[1]
rows=[]
for p in (ROOT/'data/raw/discovery_v10').rglob('*'):
 if p.suffix.upper() not in ['.TIF','.IMG','.JP2']:continue
 with rasterio.open(p) as d:
  a=d.read(1,out_shape=(min(512,d.height),min(512,d.width)),masked=True)
  v=a.compressed();v=v[np.isfinite(v)]
  rows.append({'path':str(p.relative_to(ROOT)),'sha256':hashlib.file_digest(p.open('rb'),'sha256').hexdigest(),'width':d.width,'height':d.height,'crs_wkt':d.crs.to_wkt() if d.crs else None,'transform':list(d.transform),'pixel_spacing_crs_units':list(d.res),'units':list(d.units),'nodata':d.nodata,'sampled_valid_fraction':float(len(v)/a.size),'sampled_range':[float(v.min()),float(v.max())] if len(v) else None,'quality_semantics':'uninterpreted; requires product documentation','feature_validity':'not_established','sampling':'nearest-neighbour diagnostic overview, not area or full-resolution QA'})
out=ROOT/'artifacts/reports/discovery_v10/native_source_qa.json';out.write_text(json.dumps(rows,indent=2)+'\n')
print('Inspected',len(rows),'native source rasters; no feature ranks computed')
