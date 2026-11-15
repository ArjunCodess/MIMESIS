"""Package all manuscript dependencies and the small supporting study records."""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / 'artifacts/paper'
REPORTS = ROOT / 'artifacts/reports/discovery_v10'
files = [PAPER/name for name in ['mimesis-paper.tex','main-text.tex','arxiv.sty','shot-support-summary.png','eligibility-summary.png','pit-support-summary.png','baseline-support-v11.png','site-stability.png','nili-window-overlap.png','evidence-manifest.json','v10-evidence-manifest.json','README.md']]
files += [REPORTS/name for name in ['calibration_audit_v10.json','pit_study_v10.json']]
files += [ROOT/'configs/pit_calibration_audit_v10.json']
files += [ROOT/'artifacts/reports/replication_v11'/name for name in ['terrain_finder_replay.json','scalar_baseline_transfer.json']]
files += [ROOT/'artifacts/reports/site_stability.json']
with zipfile.ZipFile(PAPER/'mimesis-overleaf.zip','w',compression=zipfile.ZIP_DEFLATED) as archive:
    for path in files:
        archive.write(path,path.name)
with zipfile.ZipFile(PAPER/'mimesis-overleaf.zip') as archive:
    if archive.testzip() is not None:
        raise ValueError('Overleaf archive integrity check failed')
print('Packaged manuscript, figures, template and supporting records; original source data excluded.')
