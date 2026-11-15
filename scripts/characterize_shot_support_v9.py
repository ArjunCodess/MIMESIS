"""Acquire bounded real PEDR exports, then characterize fixed Earth support transfer.

Run with --acquire to retrieve missing source assets. Without it, reproduce from
retained sources and emit explicit requests for missing exports. No count raster
is an input. Provider service parameters were read from the retained GDS JS.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
import sys
import time

import numpy as np
from pyproj import CRS, Geod, Transformer
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from src.shot_support import read_shots, project_shots, support_geometry, sample_earth_support

RAW = ROOT / "data/raw/shot_support_v9"
META = ROOT / "data/metadata/shot_support_v9"
DOCS = {
    "usgs_ctx": "https://stac.astrogeology.usgs.gov/docs/data/mars/ctxdtms/",
    "ode_help": "https://ode.rsl.wustl.edu/mars/pagehelp/Content/Web_Interface/Tools_Tab/MOLA_PEDR_Query_Page.htm",
    "gds": "https://oderest.rsl.wustl.edu/GDSWeb/GDSMOLAPEDR.html",
    "gds_parameters": "https://oderest.rsl.wustl.edu/GDSWeb/js/GDS.js",
    "gds_endpoint": "https://oderest.rsl.wustl.edu/GDSWeb/js/GDSMOLAPEDR.js",
    "pedr_index_label": "https://pds-geosciences.wustl.edu/mgs/mgs-m-mola-3-pedr-l1a-v1/mgsl_21xx/index/index.lbl",
    "pedr_binary_format": "https://pds-geosciences.wustl.edu/mgs/mgs-m-mola-3-pedr-l1a-v1/mgsl_21xx/label/pedrsec1.fmt"
}


def run(acquire=False):
    config = json.loads((ROOT / "configs/shot_support_v9.json").read_text())
    RAW.mkdir(parents=True, exist_ok=True); META.mkdir(parents=True, exist_ok=True)
    ledger_path = META / "sources.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else []

    def fetch(url, destination):
        response = requests.get(url, timeout=60)
        if destination.exists() and destination.read_bytes() != response.content:
            previous = destination.read_bytes()
            previous_hash = hashlib.sha256(previous).hexdigest()
            archive = destination.with_name(destination.stem + '.' + previous_hash[:16] + destination.suffix)
            archive.write_bytes(previous)
            for entry in ledger:
                if entry['path'] == destination.relative_to(ROOT).as_posix() and entry['sha256'] == previous_hash:
                    entry['path'] = archive.relative_to(ROOT).as_posix()
        destination.write_bytes(response.content)
        ledger.append({"url": response.url, "path": destination.relative_to(ROOT).as_posix(),
                       "sha256": hashlib.sha256(response.content).hexdigest(),
                       "bytes": len(response.content), "http_status": response.status_code,
                       "retrieved_at": datetime.now(timezone.utc).isoformat()})
        ledger_path.write_text(json.dumps(ledger, indent=2) + "\n")
        return response

    if acquire:
        for name, url in DOCS.items():
            dest = META / (name + (".fmt" if name.endswith("format") else ".txt"))
            if not dest.exists():
                fetch(url, dest)
    # This new catalogue asset contains residuals rather than shot heights. Retain
    # it and its processing ancestry, but never pass it into the radius parser.
    page = ROOT / "data/metadata/transfer_v9/ctx-page-001.json"
    item = json.loads(page.read_text())["features"][0]
    if acquire:
        for key in ["final_offsets", "provenance", "qa_metrics"]:
            dest = RAW / ("inventory-" + key + ".txt")
            if not dest.exists():
                fetch(item["assets"][key]["href"], dest)
    catalogue = json.loads((ROOT / "data/metadata/prospective-ctx-catalog.json").read_text())["features"]
    geod = Geod(a=config['projection_radius_m'], b=config['projection_radius_m'])
    results = []; requests_manifest = []
    for target in config['targets']:
        ident = target['id']; lon, lat = target['longitude'], target['latitude']
        crs = CRS.from_proj4(f"+proj=aeqd +lat_0={lat} +lon_0={lon} +R={config['projection_radius_m']} +units=m")
        inverse = Transformer.from_crs(crs, CRS.from_proj4(f"+proj=longlat +R={config['projection_radius_m']}"), always_xy=True)
        half = config['half_width_m']
        # Latitude extrema can occur at edge midpoints, not just corners.
        edge = np.linspace(-half, half, 161)
        perimeter_x = np.concatenate([edge, edge, np.full_like(edge, -half), np.full_like(edge, half)])
        perimeter_y = np.concatenate([np.full_like(edge, -half), np.full_like(edge, half), edge, edge])
        lons, lats = inverse.transform(perimeter_x, perimeter_y)
        query = {'query': 'molapedr', 'source': 'GDSWebMOLAPEDR', 'odemetadb': 'mars', 'o': 'j',
                 'results': 'cv', 'westlon': float(np.floor(min(lons)*1e5)/1e5), 'eastlon': float(np.ceil(max(lons)*1e5)/1e5),
                 'minlat': float(np.floor(min(lats)*1e5)/1e5), 'maxlat': float(np.ceil(max(lats)*1e5)/1e5), 'async': 't'}
        request_path = META / f"{ident}-request.json"
        status_path = META / f"{ident}-status.json"
        shot_path = RAW / f"{ident}-pedr.csv"; label_path = RAW / f"{ident}-pedr.lbl"
        request_record = {'endpoint': 'https://oderest.rsl.wustl.edu/livegds/', 'parameters': query,
                          'footprint': 'Bounding box encloses the metric 80 km square; analysis clips to square',
                          'required_missing_fields': ['original PEDR per-shot good/bad quality flag', 'PDS product ID and shot/frame index'],
                          'state': 'acquired' if shot_path.exists() else 'not_acquired'}
        prior_query = json.loads(request_path.read_text()).get('parameters') if request_path.exists() else None
        if acquire and (not shot_path.exists() or prior_query != query):
            response = requests.get(request_record['endpoint'], params=query, timeout=60)
            response.raise_for_status(); payload = response.json()
            request_record['submitted_url'] = response.url
            (META / f"{ident}-job.json").write_text(json.dumps(payload, indent=2))
            job = payload['GDSResults']['JobId']
            for _ in range(30):
                status = requests.get(request_record['endpoint'], params={'query':'status', 'o':'j', 'jobid':job}, timeout=60)
                status.raise_for_status(); payload = status.json()
                status_path.write_text(json.dumps(payload, indent=2))
                if 'ResultFiles' in payload['GDSResults']:
                    break
                time.sleep(2)
            files = payload['GDSResults'].get('ResultFiles', {}).get('ResultFile', [])
            for file in files:
                url = file['URL']
                if url.endswith('_pts_csv.csv'):
                    fetch(url, shot_path)
                elif url.endswith('_pts_csv.lbl'):
                    fetch(url, label_path)
            request_record['state'] = 'acquired' if shot_path.exists() else 'export_pending'
        request_path.write_text(json.dumps(request_record, indent=2) + '\n')
        requests_manifest.append({'target_id': ident, **request_record})
        # Source-linked nearest control subset belongs to the previously studied CTX AOI.
        control_item = min(catalogue, key=lambda f: geod.inv(lon, lat, f['properties']['proj:centroid']['lon'], f['properties']['proj:centroid']['lat'])[2])
        control_path = RAW / f"{ident}-control.csv"
        if acquire:
            for key, suffix in [('mola_csv', 'control.csv'), ('qa_metrics', 'control-qa.txt')]:
                dest = RAW / f"{ident}-{suffix}"
                if key in control_item['assets'] and not dest.exists():
                    fetch(control_item['assets'][key]['href'], dest)
        control = {'item_id': control_item['id'], 'source_url': control_item['assets'].get('mola_csv', {}).get('href'),
                   'state': 'missing_control_csv', 'scope': 'CTX alignment control subset; not complete PEDR coverage or independent CTX validation'}
        if control_path.exists():
            shots = read_shots(control_path, source_url=control['source_url'], source_kind='ctx_control_radius', units='m', body='Mars')
            control.update(state='acquired_control_subset', points=len(shots.longitude),
                           sha256=hashlib.sha256(control_path.read_bytes()).hexdigest(),
                           radius_convention='CSV radius explicitly interpreted as body-center metres, checked against Mars radius bounds; no areoid-height conversion',
                           absent_fields=['time', 'orbit', 'per-shot quality', 'footprint', 'uncertainty'])
        qa_path = RAW / f"{ident}-control-qa.txt"
        if qa_path.exists():
            control['qa_asset'] = {'source_url': control_item['assets']['qa_metrics']['href'],
                                   'sha256': hashlib.sha256(qa_path.read_bytes()).hexdigest(),
                                   'reported_ctx_minus_mola_m': {
                                       key: float(value) for key, value in re.findall(
                                           r'(Max|Min|Mean|StdDev|Median)(?: of)? difference:\s+([-+\d.]+) meters', qa_path.read_text())},
                                   'interpretation': 'Provider alignment residuals, not independent validation or per-shot uncertainty'}
        record = {'target_id': ident, 'context_id': ident, 'latitude': lat, 'longitude': lon, 'control_subset': control,
                  'source_role': 'bounded actual PEDR geometry and CTX alignment-control subset',
                  'missing_fields': ['original per-shot good/bad quality flag', 'PDS product ID', 'shot/frame index', 'calibrated footprint response', 'per-shot uncertainty']}
        if not shot_path.exists():
            record['state'] = 'missing_full_pedr_export'; results.append(record); continue
        # URL comes from the actual returned export list, never from a template.
        source_url = next(r['url'] for r in reversed(ledger) if r['path'] == shot_path.relative_to(ROOT).as_posix())
        shots = read_shots(shot_path, source_url=source_url, source_kind='ode_pedr', units='m', body='Mars', label=label_path)
        xy = project_shots(shots, lon, lat, config['projection_radius_m'])
        record.update(state='actual_pedr_support_measured', source_url=source_url,
                      full_export_point_count=len(shots.longitude),
                      raw_sha256=hashlib.sha256(shot_path.read_bytes()).hexdigest(),
                      geometry=support_geometry(shots, xy, half_width_m=half, max_time_gap_s=config['max_time_gap_s']), earth_diagnostics=[])
        for field in config['earth_fields']:
            path = ROOT / f'data/processed/{field}-projected.npz'
            dem = np.load(path)
            measured = sample_earth_support(dem['elevation'], float(dem['spacing_m']), xy[shots.attitude == 0],
                                            half_width_m=half, output_spacing_m=config['output_spacing_m'],
                                            maximum_nearest_shot_m=config['maximum_nearest_shot_m'])
            record['earth_diagnostics'].append({'earth_field': field, 'source_path': path.relative_to(ROOT).as_posix(),
                                               'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), **measured})
        results.append(record)
        print(ident, record['geometry']['retained_points'], flush=True)
    report = {'experiment_id': config['experiment_id'], 'state': 'exploratory_support_diagnostic',
              'source_manifest_path': ledger_path.relative_to(ROOT).as_posix(),
              'source_manifest_sha256': hashlib.sha256(ledger_path.read_bytes()).hexdigest() if ledger_path.exists() else None,
              'config_sha256': hashlib.sha256((ROOT/'configs/shot_support_v9.json').read_bytes()).hexdigest(),
              'config': config, 'source_documentation': DOCS, 'results': results,
              'full_pedr_requests': requests_manifest,
              'inventory_csv_assessment': {'item_id': item['id'], 'source_url': item['assets']['final_offsets']['href'],
                                           'state': 'retained_residuals_excluded_from_shot_intake',
                                           'qa_asset_state': 'provider_catalogue_qa_metrics_href_returned_404; retained error response is not QA evidence',
                                           'reason': 'Header explicitly says longitude,latitude,height diff (m); contains no radius/time/orbit/shot quality'},
              'claim_limits': ['No binned-count substitution was used.', 'ODE exports include all returned points in declared bounded queries; original good/bad quality bits and unique source shot IDs are absent.',
                               'CTX is controlled to MOLA and cannot provide fully independent validation.', 'Fixed metric geometry transfer with point interpolation measures a diagnostic, not the MEGDR gridding kernel or calibrated laser-footprint response.',
                               'These inspected Mars AOIs and Earth fields are exploratory; shot counts are not independent repetitions and no target superiority p-value is reported.']}
    report['summary'] = {
        'declared_context_count': len(config['targets']),
        'acquired_full_pedr_context_count': sum(r['state'] == 'actual_pedr_support_measured' for r in results),
        'full_pedr_shot_count': sum(r.get('full_export_point_count', 0) for r in results),
        'retained_square_attitude_zero_shot_count': sum(r.get('geometry', {}).get('retained_points', 0) for r in results),
        'acquired_control_subset_context_count': sum(r['control_subset']['state'] == 'acquired_control_subset' for r in results),
        'control_subset_point_count': sum(r['control_subset'].get('points', 0) for r in results),
        'actual_sampled_comparison_count': sum(d['state'] == 'measured_support_sensitivity' for r in results for d in r.get('earth_diagnostics', [])),
        'independent_shot_repetition_count': None,
        'claim': 'Measured exploratory source-support sensitivity; no independent geological or mapping-task validation'}
    report['limitations'] = report['claim_limits']
    report['cases'] = [{'context_id': r['context_id'], 'source_role': r['source_role'],
                        'state': r['state'], 'source_url': r.get('source_url'),
                        'metrics': r.get('geometry'), 'missing_fields': r['missing_fields'],
                        'earth_diagnostics': r.get('earth_diagnostics', [])} for r in results]
    output = json.dumps(report, indent=2, allow_nan=False) + '\n'
    for dest in [ROOT/'artifacts/reports/shot_support_v9.json', ROOT/'apps/web/public/research/shot_support_v9.json']:
        dest.parent.mkdir(parents=True, exist_ok=True); dest.write_text(output)
    lines = ['# Actual MOLA shot-support diagnostic v9', '',
             'Real ODE PEDR point exports are clipped to six existing 80 km Mars contexts. The diagnostic transfers their metric positions onto three existing NASADEM fields. It does not estimate a laser footprint response or reproduce the MEGDR interpolation kernel.', '',
             '| Mars context | Retained points | Orbits | Earth field | Common derivative coverage | Elevation RMSE, m | Slope change, degrees |',
             '|---|---:|---:|---|---:|---:|---:|']
    for r in results:
        for d in r.get('earth_diagnostics', []):
            if d['state'] == 'measured_support_sensitivity':
                lines.append(f"| {r['target_id']} | {r['geometry']['retained_points']} | {r['geometry']['orbit_count']} | {d['earth_field']} | {d['common_derivative_valid_fraction']:.3f} | {d['common_support_rmse_m']:.2f} | {d['descriptor_difference']['median_slope_deg']:.3f} |")
    lines += ['', '| CTX control subset | Points | Provider mean difference, m | Provider median difference, m |',
              '|---|---:|---:|---:|']
    for r in results:
        c = r['control_subset']; qa = c.get('qa_asset', {}).get('reported_ctx_minus_mola_m', {})
        lines.append(f"| {r['target_id']} | {c.get('points', 'missing')} | {qa.get('Mean', 'missing')} | {qa.get('Median', 'missing')} |")
    lines += ['', 'Provider residuals describe CTX alignment agreement with MOLA, not per-shot uncertainty or independent CTX validation. Large offsets remain visible in the report and are not repaired by the support diagnostic.', '',
              'A=0 rejects points with missing spacecraft attitude. The original per-shot good/bad quality bit is absent from these exports, so this is an unknown-quality sensitivity, not a quality-complete shot reconstruction. Orbit and time identify consecutive observations; gaps over 0.3 seconds are excluded from consecutive-spacing summaries.', '',
              'The acquired CTX radius CSVs are control subsets. The newer bounded inventory CSV is a CTX-minus-MOLA residual table, which is retained with QA and processing provenance and rejected as a shot-height source. CTX alignment to MOLA prevents fully independent elevation validation.', '',
              'All Earth comparisons use the same common derivative-valid mask per field and support pattern. Coverage loss and correlated shot sampling limit interpretation; no independent replication, uncertainty interval, rank improvement or mapping-rehearsal benefit is claimed.', '',
              'Reproduce with `python scripts/characterize_shot_support_v9.py`; acquire missing retained sources with `--acquire`. Exact queries, source hashes, PDS labels and missing-field requests are in the JSON report and `data/metadata/shot_support_v9/`.', '',
              'Sources: ' + ', '.join(f'[{k}]({v})' for k,v in DOCS.items()) + '.']
    for dest in [ROOT/'artifacts/reports/shot_support_v9.md', ROOT/'apps/web/public/research/shot_support_v9.md']:
        dest.write_text('\n'.join(lines)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--acquire', action='store_true')
    run(parser.parse_args().acquire)
