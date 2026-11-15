# Research paper

`mimesis-paper.tex` and `arxiv.sty` build the ten-page report with four source-backed figures. Author: Arjun Vijay Prakash, Grade XI, City Montessori School, Kanpur Road, Lucknow, India.

The style is George Kour's [arxiv-style](https://github.com/kourgeorge/arxiv-style), linked by the supplied Overleaf template. Its original style file is retained.

From this directory, with a TeX installation:

```sh
latexmk -pdf -interaction=nonstopmode -halt-on-error -outdir=build mimesis-paper.tex
```

From the repository root, `python scripts/package_paper_sources.py` creates a standalone Overleaf package containing the manuscript, style, four figures and small supporting records. Original source rasters and restricted cave data are excluded.

The report distinguishes source failures, an attributed ranking replication and exploratory support sensitivity from the unfinished confirmatory analogue study. It establishes no new geological analogue or base-safety result.
