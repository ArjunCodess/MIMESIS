# Seven-slide pitch

`mimesis-pitch.pdf` is the seven-slide presentation. Its LaTeX Beamer source uses Inter Tight and Newsreader, centered headings and a 16:9 page. All five website screenshots were supplied by Arjun Vijay Prakash. The language is written for a general audience; the paper retains the technical definitions.

Build from this directory:

```sh
latexmk -xelatex -interaction=nonstopmode -halt-on-error -outdir=build mimesis-pitch.tex
```

To rebuild the PDF, editable PowerPoint export and source archive together, install the presentation dependency and run these commands from the repository root. XeLaTeX and `latexmk` must also be installed.

```sh
python -m pip install -e ".[presentation]"
python scripts/build_presentation.py
```

The [editable Google Slides copy](google-slides.md) is saved separately in the author's Google account. Local rebuilds do not update that copy.

`python scripts/package_presentation.py`, run from the repository root, creates a standalone source archive with the images and fonts included. [Speaker notes](speaker-notes.md) include the speaking script and the evidence for each judging criterion.

The chart shows, for each target, the largest move between winning locations when map scale changes and when the comparison method changes. It is drawn from `artifacts/reports/site_stability.json`; the distance axis is linear near zero and logarithmic farther away.

The bundled fonts are static instances of the Google Fonts Inter Tight and Newsreader variable fonts. Their original SIL Open Font Licenses are included in `fonts/`.
