"""Join catalogue identities to actual published DTM polygons, retaining source conflicts."""
from pathlib import Path
import csv,hashlib,io,json,re
import xml.etree.ElementTree as ET
from shapely.geometry import Point,Polygon
from shapely.affinity import translate
from shapely.strtree import STRtree
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
folder=ROOT/'data/raw/discovery_v11/mars/mgc3'
ns={'p':'http://pds.nasa.gov/pds4/pds/v1'}
label=ET.parse(folder/'data/Mars_Cave_Catalog.xml')
table=label.find('.//p:Table_Delimited',ns)
offset=int(table.findtext('p:offset',namespaces=ns));expected_records=int(table.findtext('p:records',namespaces=ns))
fields=[n.findtext('p:name',namespaces=ns) for n in table.findall('.//p:Field_Delimited',ns)]
if fields!=['ID_Tag','Longitude','Latitude','Type_Code','Priority','APC_Diameter','APC_Depth','Comment']:
    raise ValueError('Unexpected PDS catalogue field layout')
path=folder/'data/Mars_Cave_Catalog.csv';contents=path.read_bytes()
records=list(csv.reader(io.StringIO(contents[offset:].decode('utf-8'))))
if len(records)!=expected_records or any(len(row)!=8 for row in records):
    raise ValueError('Catalogue record count or field count disagrees with PDS label')
main={row[0]:dict(zip(fields,row)) for row in records}
if len(main)!=len(records):raise ValueError('Duplicate catalogue identity')
with (folder/'miscellaneous/Mars_Cave_Catalog_shapefile.csv').open(newline='') as stream:
    geometry_rows=list(csv.DictReader(stream))
if len(geometry_rows)!=expected_records or {r['Label:string'] for r in geometry_rows}!=set(main):
    raise ValueError('Geometry representation disagrees on catalogue identities')
candidates=[]
for row in geometry_rows:
    identifier=row['Label:string'];original=main[identifier]
    lon,lat=float(row['longitude']),float(row['latitude'])
    if not 0<=lon<=360 or not -90<=lat<=90:raise ValueError('Invalid catalogue coordinates')
    delta=[lon-float(original['Longitude']),lat-float(original['Latitude'])]
    if max(abs(v) for v in delta)>.001:raise ValueError('Large disagreement between published coordinate representations')
    diameter_text=row['APC_Diameter:string']
    if diameter_text.lower() in ['', 'n/a']:diameters=[]
    elif re.fullmatch(r'\d+(?:\.\d+)?(?:x\d+(?:\.\d+)?)?',diameter_text):diameters=[float(v) for v in diameter_text.split('x')]
    else:raise ValueError('Unknown diameter notation: '+diameter_text)
    diameter=max(diameters) if diameters else None
    candidates.append({'id':identifier,'longitude':lon,'latitude':lat,'type':row['TypeCode:string'],'priority':row['Priority:string'],
                       'diameter_m':diameter,'published_diameter_text':diameter_text,'published_axes_m':diameters,'comment':row['Comment:string'],'coordinate_difference_degrees_from_main_table':delta,
                       'coordinate_source':'Published shapefile-export CSV; main-table position corroborated, finer decimals retained'})
html_path=ROOT/'data/metadata/discovery_v11/hirise-dtm-list.html';html=html_path.read_text()
polygons={}
for identifier,text in re.findall(r'polygons\["([^"]+)"\]\s*=\s*\[(.*?)\];',html,flags=re.S):
    numbers=[float(v) for v in re.findall(r'-?\d+(?:\.\d+)?',text)]
    if len(numbers)<6 or len(numbers)%2:raise ValueError('Malformed published DTM polygon')
    polygons[identifier]=np.asarray(numbers).reshape(-1,2)
title_records=json.loads((ROOT/'data/metadata/discovery_v11/mars-dtm-inventory.json').read_text())
shapes=[];shape_ids=[];invalid_polygons=[]
for identifier,xy in polygons.items():
    anchor=xy[0,0]
    polygon=Polygon(np.column_stack([anchor+(xy[:,0]-anchor+180)%360-180,xy[:,1]]))
    if not polygon.is_valid:
        invalid_polygons.append(identifier);continue
    for shift in [-360,0,360]:
        shapes.append(translate(polygon,xoff=shift));shape_ids.append(identifier)
tree=STRtree(shapes)
hits=[]
for candidate in candidates:
    point=Point(candidate['longitude'],candidate['latitude'])
    overlapping=sorted({shape_ids[int(index)] for index in tree.query(point,predicate='intersects')})
    if overlapping:hits.append({**candidate,'dtm_products':overlapping,'state':'point_intersection_only; rim and full exterior coverage unverified'})
declared_size=int(label.findtext('.//p:File/p:file_size',namespaces=ns))
declared_md5=label.findtext('.//p:File/p:md5_checksum',namespaces=ns)
report={'catalogue_records':len(candidates),'dtm_polygons':len(polygons),'invalid_dtm_polygons_not_joined':invalid_polygons,'catalogue_features_in_any_dtm':len(hits),
        'distinct_intersecting_dtms':len({p for hit in hits for p in hit['dtm_products']}),'hits':hits,
        'source_issues':{'main_csv_header':contents[:offset].decode('ascii').strip(),'field_layout_used':'PDS XML field numbers, not the inconsistent header',
                         'declared_file_size':declared_size,'actual_file_size':len(contents),'declared_md5':declared_md5,'actual_md5':hashlib.md5(contents).hexdigest(),
                         'pds_manifest_matches_file':declared_size==len(contents) and declared_md5==hashlib.md5(contents).hexdigest(),
                         'maximum_coordinate_difference_degrees':float(max(max(abs(v) for v in c['coordinate_difference_degrees_from_main_table']) for c in candidates)),
                         'interpretation':'Archive extracted CRC-clean from the official resource. Stale PDS size/checksum and inconsistent CSV header are preserved; matching IDs and nearby coordinates in the separate geometry representation corroborate identity, not rim accuracy.'},
        'sources':{'archive_url':'https://astrogeology.usgs.gov/ckan/dataset/c2960f77-ee20-4cc6-ac85-abbecc0fc7f6/resource/ccd54fb2-9a50-46bf-8971-80c241bb2f40/download/mars_cave_catalog.zip',
                   'archive_sha256':hashlib.file_digest((folder.parent/'mars_cave_catalog.zip').open('rb'),'sha256').hexdigest(),
                   'dtm_catalogue_url':'https://www.uahirise.org/hiwish/maps/dtms.jsp','dtm_catalogue_sha256':hashlib.file_digest(html_path.open('rb'),'sha256').hexdigest()},
        'limits':'Catalogue points are candidate cave entrances, not confirmed caves. Polygon overlap is not native terrain validity or complete exterior coverage.'}
out=ROOT/'artifacts/reports/discovery_v11';out.mkdir(parents=True,exist_ok=True)
(out/'mars_cave_dtm_intersections.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
(ROOT/'data/metadata/discovery_v11/mgc3-feature-inventory.json').write_text(json.dumps(candidates,indent=2)+'\n')
print('Catalogue records',len(candidates),'DTM polygons',len(polygons),'candidate point overlaps',len(hits),'distinct products',report['distinct_intersecting_dtms'])
for hit in hits:print(hit['id'],hit['longitude'],hit['latitude'],hit['type'],hit['diameter_m'],hit['dtm_products'])
print('Source issues:',report['source_issues'])
