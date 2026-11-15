"""Inventory exact catalogue identities before choosing prospective feature cases."""
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin
import hashlib,json,re
import requests

ROOT=Path(__file__).resolve().parents[1]
META=ROOT/'data/metadata/discovery_v11';META.mkdir(parents=True,exist_ok=True)

class Tables(HTMLParser):
    def __init__(self):
        super().__init__();self.rows=[];self.row=None;self.cell=None;self.links=[]
    def handle_starttag(self,tag,attrs):
        if tag=='tr':self.row=[]
        if tag in ['td','th'] and self.row is not None:self.cell=[]
        if tag=='a':
            href=dict(attrs).get('href','')
            if href:self.links.append(href)
    def handle_data(self,data):
        if self.cell is not None:self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ['td','th'] and self.cell is not None:
            self.row.append(' '.join(' '.join(self.cell).split()));self.cell=None
        if tag=='tr' and self.row is not None:
            if self.row:self.rows.append(self.row)
            self.row=None

session=requests.Session()
url='https://lroc.im-ldi.com/atlases/pits/list'
r=session.get(url,timeout=60);r.raise_for_status();(META/'lunar-atlas-list.html').write_bytes(r.content)
parser=Tables();parser.feed(r.text)
ids=sorted({int(href.rstrip('/').rsplit('/',1)[-1]) for href in parser.links if re.search(r'/atlases/pits/\d+$',href)})
print('Lunar atlas identities:',len(ids),flush=True)

def inspect(identifier):
    page=META/f'lunar-atlas-{identifier}.html'
    source=f'https://lroc.im-ldi.com/atlases/pits/{identifier}'
    if page.exists():content=page.read_bytes()
    else:
        response=requests.get(source,timeout=60)
        if response.status_code!=200:return {'atlas_id':identifier,'url':source,'state':'access_failed','http_status':response.status_code}
        content=response.content;page.write_bytes(content)
    parsed=Tables();parsed.feed(content.decode('utf-8',errors='replace'))
    fields={row[0]:row[1] for row in parsed.rows if len(row)==2}
    return {'atlas_id':identifier,'url':source,'state':'metadata_inspected','fields':fields,
            'sha256':hashlib.sha256(content).hexdigest(),'source_path':page.relative_to(ROOT).as_posix(),
            'exposure':'Catalogue text and dimensions only; no new terrain pixel values or outcomes inspected'}

with ThreadPoolExecutor(max_workers=8) as pool:
    lunar=list(pool.map(inspect,ids))
(META/'lunar-feature-inventory.json').write_text(json.dumps(lunar,indent=2)+'\n')
dtm_cases=[row for row in lunar if row.get('fields',{}).get('DTMs','').startswith('NAC_DTM')]
print('Atlas entries listing DTMs:',len(dtm_cases),flush=True)
for row in dtm_cases:print(row['atlas_id'],row['fields'].get('Name'),row['fields'].get('DTMs'),flush=True)

url='https://www.uahirise.org/hiwish/maps/dtms.jsp'
r=requests.get(url,timeout=60);r.raise_for_status();(META/'hirise-dtm-list.html').write_bytes(r.content)
parser=Tables();parser.feed(r.text)
mars=[{'title':row[0],'product_id':row[1],'latitude_product_center':row[2],'longitude_product_center':row[3],'fields':row} for row in parser.rows if len(row)>=4 and row[1].startswith('DTE')]
pit_rows=[row for row in mars if re.search(r'pit|cave|skylight|collapse',row['title'],flags=re.I)]
(META/'mars-dtm-inventory.json').write_text(json.dumps({'url':url,'sha256':hashlib.sha256(r.content).hexdigest(),'total_dtms':len(mars),'pit_or_collapse_title_rows':pit_rows,'qualification':'Title filter only; product centers are not feature centers'},indent=2)+'\n')
print('Mars DTM rows:',len(mars),'pit/collapse title hits:',len(pit_rows),flush=True)
for row in pit_rows:print(row['title'],row['product_id'],flush=True)
