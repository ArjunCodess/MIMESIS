"""Find native 3DEP sources for twelve named entrance locators in four settings.

These are intake seeds. Distinct names do not establish independent pit cases.
"""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / 'data/metadata/discovery_v11'
WANTED = {
    'craters_of_the_moon': ['Indian Cave', 'Beauty Cave', 'Dewdrop Cave'],
    'el_malpais': ['Big Skylight Cave', 'Giant Ice Cave', 'Ice Cave'],
    'lava_beds': ['Skull Cave', 'Valentine Cave', 'Sentinel Cave (Upper Entrance)'],
    'newberry': ['Boyd Cave', 'Skeleton Cave', 'Arnold Ice Cave'],
}


def query(seed):
    lon, lat = seed['longitude'], seed['latitude']
    response = requests.get('https://tnmaccess.nationalmap.gov/api/v1/products', params={
        'bbox': f'{lon-.001},{lat-.001},{lon+.001},{lat+.001}',
        'datasets': 'Digital Elevation Model (DEM) 1 meter', 'max': 30, 'outputFormat': 'JSON'}, timeout=60)
    response.raise_for_status()
    payload = response.json()
    filename = seed['id'] + '-tnm.json'
    (META / filename).write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    result = {**seed, 'query_url': response.url, 'catalogue_path': (META / filename).relative_to(ROOT).as_posix(),
              'terrain_products': [{key: item.get(key) for key in ['title', 'downloadURL', 'metaUrl', 'publicationDate', 'sourceId', 'boundingBox']}
                                   for item in payload.get('items', [])],
              'state': 'source_candidates_found' if payload.get('items') else 'no_one_metre_products_returned'}
    print(seed['region'], seed['name'], len(result['terrain_products']), 'products', flush=True)
    return result


if __name__ == '__main__':
    inventory = json.loads((META / 'earth-cave-locator-inventory.json').read_text())
    seeds = []
    for region in inventory['regions']:
        for name in WANTED[region['region']]:
            seeds.append(next(item for item in region['locators'] if item['name'] == name))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(query, seeds))
    (META / 'earth-feature-tile-inventory.json').write_text(json.dumps({
        'cases': results, 'scope': 'Twelve source-intake seeds; no rims, fine terrain outcomes or selection ranks read',
        'setting_change': 'Newberry is an additional US source setting; it does not establish completion of the proposed Lanzarote route',
        'eligibility': 'Requires independent mapped landforms, process evidence, source QA and source-ancestry grouping'}, indent=2) + '\n', encoding='utf-8')
