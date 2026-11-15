# Seven-slide pitch

`mimesis-pitch.pdf` is the presentation. `mimesis-pitch.tex` uses LaTeX Beamer's default theme and a 16:9 page. The deck includes actual local-build screenshots of Explore, Evidence, Methods, Data and the lunar pit screen, captured on 15 November 2026.

Build from this directory:

```sh
latexmk -pdf -interaction=nonstopmode -halt-on-error -outdir=build mimesis-pitch.tex
```

The scientific figure refers to the neighboring paper directory. `python scripts/package_presentation.py`, run from the repository root, creates a standalone source archive with that dependency included. [Speaker notes](speaker-notes.md) add context without shrinking the slide text. The paper and measured JSON contain the complete methods and source ledger.
