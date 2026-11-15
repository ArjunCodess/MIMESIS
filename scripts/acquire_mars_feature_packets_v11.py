"""Acquire every catalogue/DTM intersection without reading fine terrain outcomes."""
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin
import hashlib,json
import requests

ROOT=Path(__file__).resolve().parents[1]
RAW=ROOT/'data/raw/discovery_v11/mars';META=ROOT/'data/metadata/discovery_v11'
joined=json.loads((ROOT/'artifacts/reports/discovery_v11/mars_cave_dtm_intersections.json').read_text())
products=sorted({p for row in joined['hits'] for p in row['dtm_products']})

class Links(HTMLParser):
    def __init__(self):super().__init__();self.links=[]
    def handle_starttag(self,tag,attrs):
        if tag=='a' and dict(attrs).get('href'):self.links.append(dict(attrs)['href'])

def acquire(product):
    # The catalogue popup names the same released product and its first image.
    parts=product.split('_');first=f'ESP_{parts[1]}_{parts[2]}'
    page='https://www.uahirise.org/dtm/dtm.php?ID='+first
    response=requests.get(page,timeout=60)
    if response.status_code!=200:return {'product':product,'page':page,'state':'catalogue_access_failed','http_status':response.status_code}
    (META/(product+'-page.html')).write_bytes(response.content)
    links=Links();links.feed(response.text)
    terrain=sorted({urljoin(page,u) for u in links.links if u.endswith(product+'.IMG')})
    ortho=sorted({urljoin(page,u) for u in links.links if u.upper().endswith('.JP2') and 'ORTHO' in u.upper()})
    if len(terrain)!=1:return {'product':product,'page':page,'state':'terrain_link_not_unique','links':terrain}
    # One stereo-source ortho is a selection/geometry input, not independent corroboration.
    selected=terrain+ortho[:1]
    output=RAW/product;output.mkdir(exist_ok=True)
    records=[]
    for url in selected:
        target=output/url.rsplit('/',1)[-1]
        # Reuse the already acquired Elysium source without duplicating its bytes.
        existing=ROOT/'data/raw/discovery_v10/mars'/target.name
        if existing.exists():target=existing
        if not target.exists():
            r=requests.get(url,stream=True,timeout=(30,120));r.raise_for_status()
            partial=target.with_suffix(target.suffix+'.part')
            with partial.open('wb') as stream:
                for chunk in r.iter_content(1024*1024):stream.write(chunk)
            if r.headers.get('Content-Length') and partial.stat().st_size!=int(r.headers['Content-Length']):raise ValueError('Incomplete download '+url)
            partial.replace(target)
        records.append({'url':url,'path':target.relative_to(ROOT).as_posix(),'bytes':target.stat().st_size,'sha256':hashlib.file_digest(target.open('rb'),'sha256').hexdigest()})
        print(product,target.name,target.stat().st_size,flush=True)
    return {'product':product,'page':page,'state':'acquired_not_measured','assets':records,'source_ancestry':'Ortho uses the DTM stereo observations; not an independent validation acquisition','exposure':'Native terrain arrays not decoded by this acquisition step'}

with ThreadPoolExecutor(max_workers=3) as pool:
    records=list(pool.map(acquire,products))
(META/'mars-feature-source-intake.json').write_text(json.dumps(records,indent=2)+'\n')
print('Acquisition packets',len(records),flush=True)
