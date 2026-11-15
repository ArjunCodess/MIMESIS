"""Package Git-visible source and the static build, excluding ignored local data."""
from pathlib import Path
import hashlib
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
output = ROOT / 'artifacts/mimesis-research-release.zip'
listed = subprocess.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT, capture_output=True, check=True).stdout
paths = {ROOT / value.decode('utf-8') for value in listed.split(b'\0') if value}
paths.update(path for path in (ROOT / 'apps/web/dist').rglob('*') if path.is_file())
with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for path in sorted(paths):
        if path.is_file() and path != output:
            archive.write(path, path.relative_to(ROOT))
with zipfile.ZipFile(output) as archive:
    failed = archive.testzip()
    if failed:
        raise ValueError('Release CRC failure: ' + failed)
    for name in archive.namelist():
        if name.startswith(('data/raw/', 'data/quarantine/')) or 'node_modules/' in name or name.endswith(('.f32', '.rar', '.laz', '.las')):
            raise ValueError('Restricted or generated input in release: ' + name)
    for name in ['bundle.json', 'discovery.json.gz', 'replication_v11.json', 'mimesis-paper.pdf']:
        expected = (ROOT / 'apps/web/public/research' / name).read_bytes()
        for folder in ['apps/web/public/research', 'apps/web/dist/research']:
            if archive.read(folder + '/' + name) != expected:
                raise ValueError('Release record differs from source: ' + folder + '/' + name)
digest = hashlib.file_digest(output.open('rb'), 'sha256').hexdigest()
output.with_suffix('.zip.sha256').write_text(digest + '  ' + output.name + '\n', encoding='utf-8')
print(f'Release: {output} ({output.stat().st_size / 1024**2:.1f} MiB)')
print('SHA256:', digest)
