"""Acquire the v10 pilot without promoting catalogue availability to feature validity."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from html.parser import HTMLParser
import hashlib
import json
import requests

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / 'data/metadata/discovery_v10'
RAW = ROOT / 'data/raw/discovery_v10'
REPORT = ROOT / 'artifacts/reports/discovery_v10'

class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.urls = []
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.urls.extend(v for k,v in attrs if k == 'href')

def acquire(job):
    body, page, suffixes = job
    response = requests.get(page, timeout=60)
    response.raise_for_status()
    (META / (body + '-catalogue.html')).write_text(response.text, encoding='utf-8')
    links = Links(); links.feed(response.text)
    selected = sorted({urljoin(page, u) for u in links.urls if any(u.upper().endswith(s) for s in suffixes)})
    records = []
    for url in selected:
        target = RAW / body / url.rsplit('/',1)[-1]
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            r = requests.get(url, timeout=(30,120), stream=True); r.raise_for_status()
            partial = target.with_suffix(target.suffix+'.part')
            with partial.open('wb') as f:
                for block in r.iter_content(1024*1024): f.write(block)
            if r.headers.get('Content-Length') and partial.stat().st_size != int(r.headers['Content-Length']):
                raise ValueError('Incomplete source: '+url)
            partial.replace(target)
        records.append({'url':url,'path':str(target.relative_to(ROOT)), 'bytes':target.stat().st_size,'sha256':hashlib.file_digest(target.open('rb'),'sha256').hexdigest()})
        print(body,target.name,target.stat().st_size,flush=True)
    return {'body':body,'catalogue':page,'assets':records,'state':'acquired_unvalidated','feature_polygon':None}

def main():
    for path in [META,RAW,REPORT]:path.mkdir(parents=True,exist_ok=True)
    jobs=[('moon','https://data.lroc.im-ldi.com/lroc/view_rdr_product/NAC_DTM_TRANQPIT1',['TRANQPIT1.TIF','TRANQPIT1.LBL']),
          ('moon_quality','https://data.lroc.im-ldi.com/lroc/view_rdr_product/NAC_DTM_TRANQPIT1_CONF',['.TIF','.LBL']),
          ('mars','https://www.uahirise.org/dtm/dtm.php?ID=ESP_046730_2110',['DTEEC_046730_2110_055169_2110_A01.IMG','ESP_046730_2110_RED_C_01_ORTHO.JP2'])]
    results=[]
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures=[pool.submit(acquire,j) for j in jobs]
        for job,future in zip(jobs,futures):
            error=future.exception()
            results.append({'body':job[0],'state':'acquisition_failed','error':str(error)} if error else future.result())
            (META/'sources.json').write_text(json.dumps(results,indent=2)+'\n')
    earth=[]
    for name,bbox in [('craters_of_the_moon',[-113.65,43.35,-113.4,43.6]),('el_malpais',[-108.15,34.75,-107.9,35.0]),('lava_beds',[-121.65,41.6,-121.4,41.85])]:
        r=requests.get('https://tnmaccess.nationalmap.gov/api/v1/products',params={'bbox':','.join(map(str,bbox)),'datasets':'Digital Elevation Model (DEM) 1 meter','max':100,'outputFormat':'JSON'},timeout=60)
        record={'region':name,'query_url':r.url,'http_status':r.status_code,'scope':'proposed region bounds, not verified pit coordinates'}
        if r.ok:
            payload=r.json(); (META/(name+'-tnm.json')).write_text(json.dumps(payload,indent=2)+'\n');record.update(total=payload.get('total'),items_returned=len(payload.get('items',[])))
        earth.append(record)
    status={'experiment':'discovery_v10','generated_at':datetime.now(timezone.utc).isoformat(),'planetary_sources':results,'earth_inventory':earth,'claim':'No triad nominated; exact feature polygons, source QA, independent corroboration and prior-art clearance remain required.'}
    (REPORT/'feasibility.json').write_text(json.dumps(status,indent=2)+'\n')
    print(json.dumps(earth,indent=2))
if __name__ == '__main__':main()
