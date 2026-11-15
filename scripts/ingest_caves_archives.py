"""Extract local CAVES packages and audit native point records without georeferencing them."""
from pathlib import Path, PureWindowsPath
import argparse
import hashlib
import json
import shutil
import subprocess
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--seven-zip', type=Path, required=True)
    args = parser.parse_args()
    destination = ROOT / 'data/raw/discovery_v10/caves'
    report_dir = ROOT / 'artifacts/reports/discovery_v10'
    destination.mkdir(parents=True, exist_ok=True)
    archive_dir = destination / 'archives'
    archives = sorted(p for folder in [ROOT, archive_dir] for p in folder.glob('*.rar') if p.name.startswith(('IndianTunnel', 'Sheepridge', 'CAVES', 'Kingsbowl', 'Fieg')))
    if not archives:
        raise ValueError('No CAVES archives found in the workspace root or local raw archive directory')
    inventory_path = report_dir / 'caves_archive_inventory.json'
    previous = {row['archive']: row for row in json.loads(inventory_path.read_text())} if inventory_path.exists() else {}
    records = []
    for archive in archives:
        listing = subprocess.run([str(args.seven_zip), 'l', '-slt', str(archive)], capture_output=True, text=True, check=True).stdout
        entries = []
        for block in listing.split('----------', 1)[1].strip().split('\n\n'):
            fields = dict(line.split(' = ', 1) for line in block.splitlines() if ' = ' in line)
            if 'Path' not in fields:
                continue
            member = PureWindowsPath(fields['Path'])
            if member.drive or member.root or '..' in member.parts:
                raise ValueError(f'Unsafe archive member: {member}')
            entries.append({'path': fields['Path'], 'bytes': int(fields.get('Size', 0)), 'directory': fields.get('Folder') == '+'})
        out = destination / archive.stem
        archive_hash = hashlib.file_digest(archive.open('rb'), 'sha256').hexdigest()
        prior = previous.get(archive.name)
        if prior and prior['sha256'] == archive_hash and all(row['directory'] or (out.joinpath(*PureWindowsPath(row['path']).parts).is_file() and out.joinpath(*PureWindowsPath(row['path']).parts).stat().st_size == row['bytes']) for row in entries):
            records.append(prior)
            print(f'Reusing CRC-verified extraction: {archive.name}', flush=True)
            continue
        required = sum(row['bytes'] for row in entries)
        if shutil.disk_usage(destination).free < required:
            raise RuntimeError(f'Insufficient free disk space for {archive.name}')
        out.mkdir(exist_ok=True)
        log_path = report_dir / f'{archive.stem}-extraction.log'
        print(f'Extracting {archive.name}: {required:,} unpacked bytes', flush=True)
        with log_path.open('w', encoding='utf-8') as log:
            subprocess.run([str(args.seven_zip), 'x', '-y', '-bsp0', str(archive), f'-o{out}'], stdout=log, stderr=subprocess.STDOUT, check=True)
        for row in entries:
            if row['directory']:
                continue
            path = out.joinpath(*PureWindowsPath(row['path']).parts)
            if path.stat().st_size != row['bytes']:
                raise ValueError(f'Extracted size mismatch: {path}')
        records.append({'archive': archive.name, 'bytes': archive.stat().st_size, 'sha256': archive_hash, 'extracted_to': out.relative_to(ROOT).as_posix(), 'integrity': '7-Zip extraction CRC and member sizes passed', 'members': entries})
        inventory_path.write_text(json.dumps(records, indent=2) + '\n')
    inventory_path.write_text(json.dumps(records, indent=2) + '\n')
    clouds = []
    for path in sorted(destination.rglob('*.f32')):
        if path.stat().st_size % 28:
            raise ValueError(f'Incomplete seven-float record: {path}')
        points = np.memmap(path, dtype='<f4', mode='r').reshape(-1, 7)
        lower = np.full(7, np.inf)
        upper = np.full(7, -np.inf)
        invalid = 0
        for start in range(0, len(points), 1_000_000):
            chunk = points[start:start + 1_000_000]
            finite = np.isfinite(chunk)
            invalid += int((~finite.all(axis=1)).sum())
            lower = np.minimum(lower, np.min(np.where(finite, chunk, np.inf), axis=0))
            upper = np.maximum(upper, np.max(np.where(finite, chunk, -np.inf), axis=0))
        clouds.append({'path': path.relative_to(ROOT).as_posix(), 'point_count': len(points), 'nonfinite_records': invalid, 'attribute_min': lower.tolist(), 'attribute_max': upper.tolist(), 'sha256': hashlib.file_digest(path.open('rb'), 'sha256').hexdigest(), 'coordinate_reference': 'local Cartesian metres; world transform not established', 'attributes': ['x','y','z','NIR_reflectance','red','green','blue'], 'ground_classification': 'not supplied'})
        print(f'Audited {path.name}: {len(points):,} records', flush=True)
    (report_dir / 'caves_point_cloud_qa.json').write_text(json.dumps({'clouds': clouds, 'research_state': 'source inspection only; no exact rim, ground surface or withheld outcome inferred'}, indent=2) + '\n')


if __name__ == '__main__':
    main()
