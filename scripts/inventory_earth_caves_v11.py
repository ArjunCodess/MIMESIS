"""Acquire public map locators; these are search seeds, not surveyed rims."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib,json
import xml.etree.ElementTree as ET
import requests

ROOT=Path(__file__).resolve().parents[1];META=ROOT/'data/metadata/discovery_v11'
regions=[('craters_of_the_moon',[-113.56,43.43,-113.51,43.46]),
         ('el_malpais',[-108.13,34.93,-108.07,34.97]),
         ('lava_beds',[-121.65,41.65,-121.4,41.85]),
         ('newberry',[-121.22,43.89,-121.14,43.96])]
def acquire(job):
    name,bounds=job;cache_key=hashlib.sha256(json.dumps(bounds).encode()).hexdigest()[:10]
    path=META/(name+'-locator-map-'+cache_key+'.osm')
    url='https://api.openstreetmap.org/api/0.6/map'
    if not path.exists():
        r=requests.get(url,params={'bbox':','.join(map(str,bounds))},timeout=90);r.raise_for_status();path.write_bytes(r.content)
    root=ET.fromstring(path.read_bytes());nodes=[]
    for node in root.findall('node'):
        tags={t.attrib['k']:t.attrib['v'] for t in node.findall('tag')}
        if tags.get('natural') not in ['cave_entrance','sinkhole'] or not tags.get('name'):continue
        nodes.append({'id':'OSM_NODE_'+node.attrib['id'],'region':name,'name':tags['name'],
                      'latitude':float(node.attrib['lat']),'longitude':float(node.attrib['lon']),
                      'osm_version':node.attrib['version'],'osm_timestamp':node.attrib['timestamp'],
                      'source_url':'https://www.openstreetmap.org/node/'+node.attrib['id'],
                      'source_tags':tags,'source_map':path.relative_to(ROOT).as_posix(),
                      'geometry_state':'Public entrance locator, not a rim or a pit center',
                      'process_label':'requires an independent geological/park source before eligibility'})
    return {'region':name,'bbox':bounds,'map_url':url,'sha256':hashlib.file_digest(path.open('rb'),'sha256').hexdigest(),'locators':nodes}
with ThreadPoolExecutor(max_workers=2) as pool:rows=list(pool.map(acquire,regions))
(META/'earth-cave-locator-inventory.json').write_text(json.dumps({'attribution':'OpenStreetMap contributors, ODbL; locator accuracy not established','regions':rows},indent=2)+'\n')
for row in rows:print(row['region'],[(n['name'],n['latitude'],n['longitude']) for n in row['locators']],flush=True)
