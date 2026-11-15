"""Package the seven-slide Beamer source with its screenshots and figure."""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PRESENTATION = ROOT / 'artifacts/presentation'

with zipfile.ZipFile(PRESENTATION / 'mimesis-beamer.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
    source = (PRESENTATION / 'mimesis-pitch.tex').read_text(encoding='utf-8')
    archive.writestr('mimesis-pitch.tex', source.replace('../paper/site-stability.png', 'images/site-stability.png'))
    for path in sorted((PRESENTATION / 'images').glob('*.png')):
        archive.write(path, 'images/' + path.name)
    archive.write(ROOT / 'artifacts/paper/site-stability.png', 'images/site-stability.png')
    archive.write(PRESENTATION / 'speaker-notes.md', 'speaker-notes.md')
    archive.writestr('README.md', '# MIMESIS Beamer pitch\n\nSeven slides. Build with `latexmk -pdf mimesis-pitch.tex`. All images are included. Screenshots show the working local application captured on 15 November 2026.\n')
with zipfile.ZipFile(PRESENTATION / 'mimesis-beamer.zip') as archive:
    if archive.testzip() is not None:
        raise ValueError('Presentation archive integrity check failed')
print('Packaged standalone Beamer source, five application screenshots, figure and notes.')
