"""Build publication figures from the saved v9 measurement records, without acquiring data."""
from pathlib import Path
import hashlib
import json
import shutil
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'artifacts/reports'
PAPER = ROOT / 'artifacts/paper'
PUBLIC = ROOT / 'apps/web/public/research'
PAPER.mkdir(exist_ok=True)
shot = json.loads((REPORTS / 'shot_support_v9.json').read_text())
gate = json.loads((REPORTS / 'global_eligibility_v9.json').read_text())
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11, 'axes.spines.top': False, 'axes.spines.right': False, 'axes.labelcolor': '#29372e', 'text.color': '#29372e', 'savefig.facecolor': '#f5f2e9', 'axes.facecolor': '#f5f2e9', 'figure.facecolor': '#f5f2e9'})
fig, ax = plt.subplots(figsize=(9, 5.8), layout='constrained')
x = np.arange(6)
for i, (field, color) in enumerate(zip(['namib', 'mojave', 'atacama'], ['#536c55', '#a45334', '#6b7e98'])):
    values = [next(d for d in r['earth_diagnostics'] if d['earth_field'] == field)['descriptor_difference']['median_slope_deg'] for r in shot['results']]
    ax.barh(x + (i-1)*.22, values, height=.19, color=color, label=field.title())
ax.axvline(0, color='#62695d', linewidth=1)
ax.set(yticks=x, yticklabels=[f'Context {i+1}' for i in x], xlabel='Sampled minus baseline median slope (degrees)', xlim=(-.32,.025)); ax.invert_yaxis()
ax.legend(frameon=False, ncol=3, loc='lower center', bbox_to_anchor=(.5,1))
ax.grid(axis='x', alpha=.15)
fig.savefig(PAPER / 'shot-support-summary.png', dpi=200)
plt.close(fig)
counts = gate['summary']['status_counts']
fig, ax = plt.subplots(figsize=(9, 5), layout='constrained')
values = [counts[k] for k in ['excluded_terrain','excluded_observed_natural_land_upper_bound','unknown_missing_required_layers']]
ax.barh(['Terrain excluded', 'Observed natural-land\nupper bound fails', 'Required layers missing\nOutcome unknown'],values,color=['#a45334','#536c55','#87908c'],height=.55)
for i,v in enumerate(values): ax.text(v+1,i,str(v),va='center',fontsize=14)
ax.set(xlim=(0,60),xlabel='Frozen contexts, out of 100')
ax.invert_yaxis()
fig.savefig(PAPER / 'eligibility-summary.png', dpi=200)
plt.close(fig)
for name in ['shot-support-summary.png','eligibility-summary.png']:
    shutil.copy2(PAPER/name, PUBLIC/name)
shutil.copy2(REPORTS/'orbital_spectra_v9.png', PUBLIC/'orbital_spectra_v9.png')
manifest = {name: {'path': f'artifacts/reports/{name}', 'sha256': hashlib.sha256((REPORTS/name).read_bytes()).hexdigest()} for name in ['shot_support_v9.json','global_eligibility_v9.json','orbital_spectra_v9.json','transfer_v9.json']}
(PAPER/'evidence-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Built two figures and paper evidence manifest from saved measurements.')

v10_names = ['native_confidence_qa.json', 'field_survey_qa.json', 'native_source_qa.json', 'feasibility.json', 'caves_archive_inventory.json', 'caves_point_cloud_qa.json', 'caves_surface_support.json', 'registered_earth_source_qa.json', 'registered_earth_gap_source_qa.json', 'lunar_calibration_proxy.json', 'marius_calibration_proxy.json', 'calibration_audit_v10.json', 'pit_study_v10.json']
v10_manifest = {name: {'path': str((REPORTS/'discovery_v10'/name).relative_to(ROOT)).replace(chr(92), '/'), 'sha256': hashlib.sha256((REPORTS/'discovery_v10'/name).read_bytes()).hexdigest()} for name in v10_names if (REPORTS/'discovery_v10'/name).exists()}
(PAPER/'v10-evidence-manifest.json').write_text(json.dumps(v10_manifest, indent=2)+'\n')
