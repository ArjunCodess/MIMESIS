"""Check native PDS confidence bytes against the published categorical lookup.

This source audit reads no terrain elevations and produces no analogue scores.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urljoin

import numpy as np
import rasterio
import requests

from scripts.acquire_discovery_v10 import Links

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / 'data/metadata/discovery_v11'
PRODUCTS = ['IRIDIUMPIT1', 'FECNDITATS2', 'FECUNPIT', 'INGENIIPIT']


def main():
    results = []
    for product in PRODUCTS:
        base = 'NAC_DTM_' + product
        path = ROOT / 'data/raw/discovery_v10' / ('moon_' + product.lower()) / (base + '_CONF.IMG')
        with path.open('rb') as stream:
            label = stream.read(16384).decode('ascii', errors='replace')
        record_bytes = int(re.search(r'RECORD_BYTES\s*=\s*(\d+)', label)[1])
        image_record = int(re.search(r'\^IMAGE\s*=\s*(\d+)', label)[1])
        lines = int(re.search(r'\bLINES\s*=\s*(\d+)', label)[1])
        samples = int(re.search(r'LINE_SAMPLES\s*=\s*(\d+)', label)[1])
        bits = int(re.search(r'SAMPLE_BITS\s*=\s*(\d+)', label)[1])
        if bits != 8 or samples != record_bytes:
            raise ValueError(f'{product}: unexpected native byte layout')
        offset = (image_record - 1) * record_bytes
        if path.stat().st_size != offset + lines * samples:
            raise ValueError(f'{product}: label dimensions disagree with file length')
        raw = np.memmap(path, dtype='uint8', mode='r', offset=offset, shape=(lines, samples))
        counts = np.bincount(raw.ravel(), minlength=256)
        with rasterio.open(path) as dataset:
            agrees = all(np.array_equal(dataset.read(1, window=window), raw[window.toslices()])
                         for _, window in dataset.block_windows(1))
        if not agrees:
            raise ValueError(f'{product}: GDAL decoding differs from native bytes')
        page = 'https://data.lroc.im-ldi.com/lroc/view_rdr/' + base
        response = requests.get(page, timeout=60)
        response.raise_for_status()
        (META / (product + '-product-page.html')).write_text(response.text, encoding='utf-8')
        links = Links()
        links.feed(response.text)
        readme_urls = sorted({urljoin(page, value) for value in links.urls if 'README' in value.upper()})
        if len(readme_urls) != 1:
            raise ValueError(f'{product}: expected one published readme, got {readme_urls}')
        response = requests.get(readme_urls[0], timeout=60)
        response.raise_for_status()
        readme = response.text
        if 'CONFIDENCE MAP TABLE LOOKUP' not in readme or '10-14' not in readme:
            raise ValueError(f'{product}: confidence lookup needs manual review')
        (META / (product + '-readme.txt')).write_text(readme, encoding='utf-8')
        observed = np.flatnonzero(counts).tolist()
        unknown = sorted(set(observed) - {0, 1, 2, 3, 4, 10, 11, 12, 13, 14, 15})
        result = {
            'product': base, 'source_page': page, 'readme_url': readme_urls[0],
            'native_path': path.relative_to(ROOT).as_posix(),
            'native_sha256': hashlib.file_digest(path.open('rb'), 'sha256').hexdigest(),
            'readme_sha256': hashlib.sha256(response.content).hexdigest(),
            'image_offset_bytes': offset, 'shape': [lines, samples],
            'gdal_matches_direct_native_bytes': agrees,
            'histogram': {str(v): int(counts[v]) for v in observed},
            'undocumented_codes': unknown,
            'state': 'unassessable_confidence_encoding' if unknown else 'categorical_encoding_verified',
            'validation_eligible': False,
            'remaining_checks': ['exact feature identity and footprint', 'terrain finite mask',
                                 'registration', 'source artifacts', 'physical support and coverage'],
        }
        results.append(result)
        print(base, result['state'], 'range', min(observed), max(observed), flush=True)
    output = ROOT / 'artifacts/reports/discovery_v11/lunar_confidence_encoding_audit.json'
    output.write_text(json.dumps({'checked_at': datetime.now(timezone.utc).isoformat(),
                                 'scope': 'Source encoding only; no elevations or fine terrain outcomes read',
                                 'cases': results}, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
