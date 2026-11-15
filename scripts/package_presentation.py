"""Package the seven-slide Beamer source with its screenshots and figure."""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PRESENTATION = ROOT / 'artifacts/presentation'

with zipfile.ZipFile(PRESENTATION / 'mimesis-beamer.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
    source = (PRESENTATION / 'mimesis-pitch.tex').read_text(encoding='utf-8')
    archive.writestr('mimesis-pitch.tex', source)
    for path in sorted((PRESENTATION / 'images').glob('*.png')):
        archive.write(path, 'images/' + path.name)
    for path in sorted((PRESENTATION / 'fonts').iterdir()):
        archive.write(path, 'fonts/' + path.name)
    archive.write(PRESENTATION / 'speaker-notes.md', 'speaker-notes.md')
    archive.writestr('README.md', '# MIMESIS Beamer pitch\n\nSeven slides. Build with `latexmk -xelatex mimesis-pitch.tex`. All images, Inter Tight and Newsreader fonts, and their SIL Open Font Licenses are included. The five website screenshots were supplied by Arjun Vijay Prakash. The chart is derived from the project geographic stability record.\n')
with zipfile.ZipFile(PRESENTATION / 'mimesis-beamer.zip') as archive:
    if archive.testzip() is not None:
        raise ValueError('Presentation archive integrity check failed')
print('Packaged standalone Beamer source, five application screenshots, figure and notes.')
