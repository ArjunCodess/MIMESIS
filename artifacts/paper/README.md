# Research paper

`mimesis-paper.tex`, `main-text.tex` and `arxiv.sty` build the research report. Author: Arjun Vijay Prakash, Grade XI, City Montessori School, Kanpur Road, Lucknow, India.

The style is George Kour's [arxiv-style](https://github.com/kourgeorge/arxiv-style), linked by the supplied Overleaf template. Its original style file is retained.

From this directory, with a TeX installation:

```sh
latexmk -pdf -interaction=nonstopmode -halt-on-error -outdir=build mimesis-paper.tex
```

From the repository root, `python scripts/package_paper_sources.py` creates a standalone Overleaf package containing the manuscript, style, figures and small supporting records. Original source rasters and restricted cave data are excluded.

The main result distinguishes rank turnover, shared ground and scoring-contract dependence. Run `python scripts/measure_site_stability.py` to regenerate its records and figures. Earlier source failures, an attributed ranking replication and the unfinished confirmatory analogue study remain documented. No new geological analogue or base-safety result is established.
