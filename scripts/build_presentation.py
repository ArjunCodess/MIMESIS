"""Build the pitch PDF and editable export, then package the Beamer sources."""
from pathlib import Path
import runpy
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PRESENTATION = ROOT / 'artifacts/presentation'
subprocess.run(
    ['latexmk', '-xelatex', '-interaction=nonstopmode', '-halt-on-error',
     '-outdir=build', 'mimesis-pitch.tex'],
    cwd=PRESENTATION, check=True,
)
shutil.copy2(PRESENTATION / 'build/mimesis-pitch.pdf', PRESENTATION / 'mimesis-pitch.pdf')
runpy.run_path(str(ROOT / 'scripts/build_editable_presentation.py'), run_name='__main__')
runpy.run_path(str(ROOT / 'scripts/package_presentation.py'), run_name='__main__')
