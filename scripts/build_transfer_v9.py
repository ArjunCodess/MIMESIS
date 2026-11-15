"""Build actual pair feasibility and bounded official CTX metadata preflight."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import requests
from pyproj import Geod

from src.ranking import canonical_hash
from src.transfer import (allocate_controls, catalog_local_feasibility, exact_pair_diagnostics, inference, reference_gate, square_geometry)

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / 'apps/web/public/research'
META = ROOT / 'data/metadata/transfer_v9'
REPORTS = ROOT / 'artifacts/reports'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def source(path):
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def inventory(config, refresh=False):
    META.mkdir(parents=True, exist_ok=True)
    entries, pages, seen = [], [], set()
    url = config['catalog_url']
    params = {'collections': config['collection'], 'limit': config['catalog_page_limit']}
    for index in range(config['catalog_max_pages']):
        path = META / f'ctx-page-{index + 1:03d}.json'
        request_path = META / f'ctx-page-{index + 1:03d}-request.json'
        if refresh or not path.exists():
            response = requests.get(url, params=params, timeout=60)
            request_path.write_text(json.dumps({'url': response.url, 'http_status': response.status_code, 'retrieved_at': datetime.now(timezone.utc).isoformat()}, indent=2))
            path.write_bytes(response.content)
        request = read(request_path)
        pages.append({**source(path), **request})
        if request['http_status'] != 200:
            break
        page = read(path)
        for item in page['features']:
            if item.get('collection') != config['collection']:
                raise ValueError('USGS catalogue returned a different collection')
            if item['id'] in seen:
                continue
            seen.add(item['id'])
            assets = item['assets']
            dtm_key = next((key for key in ('geoid_adjusted_dem', 'dtm', 'dem') if key in assets), None)
            if dtm_key is None:
                raise ValueError('Expected CTX DTM asset is missing')
            entries.append({'id': item['id'], 'collection': item['collection'], 'geometry': item['geometry'], 'bbox': item.get('bbox'), 'dtm_asset_key': dtm_key, 'dtm_asset': assets[dtm_key], 'quality_assets': {k: v for k, v in assets.items() if k in ('qa_metrics', 'final_offsets', 'intersection_error', 'provenance')}, **catalog_local_feasibility(item)})
        next_link = next((link for link in page['links'] if link['rel'] == 'next'), None)
        if next_link is None:
            break
        if next_link.get('method', 'GET') != 'GET':
            raise ValueError('Unexpected pagination method')
        url, params = next_link['href'], None
    matched = read(META / 'ctx-page-001.json').get('numberMatched') if pages[0]['http_status'] == 200 else None
    return {'pages': pages, 'provider_number_matched': matched, 'item_count': len(entries), 'complete_catalogue': len(entries) == matched, 'items': entries, 'selection': config['catalog_selection'], 'dtm_pixels_downloaded': False}


def build(refresh=False):
    config_path = ROOT / 'configs/transfer_v9.json'
    config = read(config_path)
    v6_path = PUBLIC / 'natural_land_v6.json'
    v8_path = PUBLIC / 'global_terrain_v8.json'
    v6, v8 = read(v6_path), read(v8_path)
    exact = {}
    for buffer, experiment in v6['experiments'].items():
        candidates = experiment['candidates']
        for c in candidates:
            # The V6 centers are offsets in a shared region frame; use that exact
            # frame for its L-infinity audit, actual polygons across regions.
            c['context_geometry'] = square_geometry(c['longitude'], c['latitude'], 80000)
        exact[buffer] = {**exact_pair_diagnostics(candidates, config['slope_match_tolerance_deg'], config['relief_match_tolerance_m'], regional_frame=True), 'matching_scope': 'Slope/relief tolerances are a new V9 exploratory sensitivity, not a reproduction of all frozen V6 control rules. The zero geometry count does not depend on these tolerances.', 'eligible_count': len(candidates), 'regions': sorted({c['region_id'] for c in candidates}), 'center_span_easting_m': max(c['easting_m'] for c in candidates) - min(c['easting_m'] for c in candidates), 'center_span_northing_m': max(c['northing_m'] for c in candidates) - min(c['northing_m'] for c in candidates)}
    catalog = inventory(config, refresh)
    inspected = v8['targets']
    geod = Geod(a=3396190, b=3396190)
    for item in catalog['items']:
        exposed = [t['id'] for t in inspected if t['body'] == 'Mars' and geod.inv(item['longitude'], item['latitude'], t['longitude'], t['latitude'])[2] < 120000]
        item['prior_context_exposure'] = exposed
        item['target_state'] = 'excluded_prior_context_exposure' if exposed else 'unfrozen_metadata_candidate'
        item['reference_gate'] = reference_gate({})
    inventory_path = META / 'ctx-inventory.json'
    inventory_path.write_text(json.dumps(catalog, indent=2), encoding='utf-8')
    # Full densified local/context polygons remain inspectable in the metadata
    # inventory. The public ledger keeps the source footprint and source hashes.
    catalog = {**catalog, 'inventory_source': source(inventory_path), 'items': [{key: value for key, value in item.items() if key not in ('local_geometry', 'context_geometry')} for item in catalog['items']]}
    eligibility_path = PUBLIC / 'global_eligibility_v9.json'
    eligibility = read(eligibility_path) if eligibility_path.exists() else None
    if eligibility and eligibility['frame_sha256'] != v8['frame_sha256']:
        raise ValueError('V9 eligibility and V8 descriptors must use the identical frozen frame')
    # Missing eligibility never falls back to V8 terrain-only candidates.
    qualified = {b['id'] for b in eligibility['blocks'] if b.get('eligible') is True} if eligibility else set()
    candidates = [c for c in v8['candidates'] if c['id'] in qualified]
    nominations = []
    for target_id, ranking in sorted(v8['rankings'].items()):
        top = next((r for r in ranking['candidates'] if r['id'] in qualified), None)
        if top:
            nominations.append({'target_id': target_id, 'candidate_id': top['id']})
    controls = allocate_controls(nominations, candidates, config['slope_match_tolerance_deg'], config['relief_match_tolerance_m'])
    cases = []
    for target in inspected:
        pair = next((p for p in controls['pairs'] if p['target_id'] == target['id']), None)
        cases.append({'target_id': target['id'], 'body': target['body'], 'exposure': 'already_inspected_not_blind', 'pair': pair, 'state': 'missing_data_abstention', 'missing': ['qualified_unused_Earth_pair'] if pair is None else ['independent_fine_validation'], 'reference': reference_gate({}), 'human_rehearsal': 'no_controlled_intervention_or_independent_participants'})
    report = {'id': config['id'], 'status': 'exploratory_feasibility_with_missing_data_abstention', 'generated_at': datetime.now(timezone.utc).isoformat(), 'config': config, 'sources': [source(p) for p in (config_path, v6_path, v8_path, ROOT / 'configs/prospective_targets_v5.json', ROOT / 'src/transfer.py', Path(__file__).resolve())] + ([source(eligibility_path)] if eligibility else []), 'v6_exact_feasibility': exact, 'catalogue': catalog, 'earth_eligibility': {'state': 'measured_gate_consumed' if eligibility else 'missing_eligibility_abstention', 'qualified_count': len(candidates), 'missing_eligibility_is_not_pass': True}, 'global_pair_diagnostics': exact_pair_diagnostics(candidates, config['slope_match_tolerance_deg'], config['relief_match_tolerance_m']), 'controls': controls, 'cases': cases, 'inference': inference([], missing_pairs=len(cases)), 'summary': {'existing_case_count': len(cases), 'qualified_earth_blocks': len(candidates), 'complete_transfer_pairs': 0, 'catalogue_item_count': catalog['item_count'], 'geometry_feasible_items': sum(i['geometry_feasible'] for i in catalog['items']), 'metadata_candidates_outside_prior_contexts': sum(i['geometry_feasible'] and not i['prior_context_exposure'] for i in catalog['items']), 'new_targets_frozen': 0}, 'claim': 'Exact bounded feasibility and metadata inventory only; no new blind validation, analogue discovery, equivalence or human utility established', 'source_limits': ['CTX is aligned to MOLA: fully independent ancestry is not established', '20m posting is not effective resolution; fixed 100/200/300m support sensitivities precede future evaluation', 'GLO30 DEM alone cannot establish FLM/HEM/EDM/WBM filled ancestry; independence unknown', 'SIM3464 Jezero is inspected calibration only; no inherited universal contact tolerance', 'Local 20km stereo coverage is distinct from coarse 80km MOLA context ranking; no 80% fine context gate', 'Metadata-only local coverage retains unknown valid pixels and reference availability', 'No complete pairs currently means missing-data abstention, not a negative analogue result']}
    report['record_hash'] = canonical_hash(report)
    REPORTS.mkdir(parents=True, exist_ok=True)
    for path in (REPORTS / 'transfer_v9.json', PUBLIC / 'transfer_v9.json'):
        path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    public_summary = {**report, 'catalogue': {k: v for k, v in catalog.items() if k != 'items'}, 'source_report_hash': report['record_hash']}
    public_summary['record_hash'] = canonical_hash({k: v for k, v in public_summary.items() if k != 'record_hash'})
    for path in (REPORTS / 'transfer_v9.summary.json', PUBLIC / 'transfer_v9.summary.json'):
        path.write_text(json.dumps(public_summary, indent=2), encoding='utf-8')
    summary = report['summary']
    markdown = f"# Transfer v9 feasibility\n\nV6 exact enumeration retains {exact['500']['eligible_count']} and {exact['1000']['eligible_count']} eligible Namib windows, with {exact['500']['geometry_pass']} and {exact['1000']['geometry_pass']} separated pairs among {exact['500']['total_pairs']} and {exact['1000']['total_pairs']} pairs. Center spans are 12km by 54km. Matching tolerances cannot repair their overlapping 80km contexts. The reported slope/relief diagnostics use a new V9 proposal of 1 degree and 100m, not all frozen V6 control rules.\n\nThe new bounded official CTX inventory contains {catalog['item_count']} items of {catalog['provider_number_matched']} reported by the collection. Actual polygon intersection gives {summary['geometry_feasible_items']} nominal 20km-local coverage candidates, of which {summary['metadata_candidates_outside_prior_contexts']} lie outside conservatively excluded inspected contexts. These are metadata feasibility counts, with unknown valid pixels and no frozen evaluation targets.\n\nThe V9 Earth gate supplies {len(candidates)} qualified blocks. There are zero completed transfer pairs and all {len(cases)} inspected target cases abstain. Pending observation acquisition is not a scientific null. All metadata pages, query URLs and hashes are retained. No large DTM or spectral cube was acquired.\n\nFine morphology retains Wasserstein-1 on slope and planar Laplacian with its existing normalization. The fixed support sensitivity is 100/200/300m; 20m CTX posting does not establish resolution. CTX uses MOLA control, and GLO30 filled ancestry remains unknown. Contact scoring requires an independently authored reference with coverage, accuracy, method, blinding and tolerance justification. Human utility requires a controlled rehearsal intervention with independent blinded participants.\n\n[Official USGS CTX processing and quality documentation](https://stac.astrogeology.usgs.gov/docs/data/mars/ctxdtms/) documents missing stereo pixels, MOLA control and the difference between posting and effective detail.\n"
    for path in (REPORTS / 'transfer_v9.md', PUBLIC / 'transfer_v9.md'):
        path.write_text(markdown, encoding='utf-8')
    print(json.dumps(report['summary'], indent=2))
    return report


if __name__ == '__main__':
    build('--refresh' in sys.argv)
