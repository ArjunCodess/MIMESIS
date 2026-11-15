# MIMESIS

An Earth, Moon and Mars terrain research workspace with an interactive explorer, source-linked measurements and a reproducible LaTeX paper.

Built by [Arjun Vijay Prakash](https://arjuncodess.is-a.dev/), Grade XI, City Montessori School, Kanpur Road, Lucknow, India.

## Run

Use Python 3.11+ and Node.js 22+.

```sh
python -m pip install -e ".[test]"
python scripts/prepare_checkout.py
npm ci
npm run build
python -m uvicorn services.api.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. The API reference is at `/docs`. For frontend development, run `npm run dev`.

## Research

The four views are Explore, Evidence, Methods and Data. The [paper](artifacts/paper/mimesis-paper.pdf) and [LaTeX source](artifacts/paper/mimesis-paper.tex) explain the measurements and their limits.

The geographic study compares 3,693 Earth windows across six targets, two scoring contracts and two supports. Nili Fossae's top tens share no IDs across supports, yet the winning footprints have 73.9% intersection-over-union. Changing the scoring contract moves Jezero and Syrtis winners between Namibia and Chile, over 8,300 km. These are exploratory geographic findings; geological relevance and field utility remain unvalidated.

The [submission](artifacts/submission/submission.md) includes the judging-criteria evidence, demonstration script and deliverables. [Location GeoJSON](apps/web/public/research/site-shortlist.geojson) contains candidate footprints and validation status.

The [seven-slide pitch](artifacts/presentation/mimesis-pitch.pdf) uses LaTeX Beamer and actual application screenshots. Its [source and build instructions](artifacts/presentation/README.md) accompany the PDF.

Scientific records retain source identities, hashes, masks and exclusions. Missing terrain is not treated as smooth ground, and a ranking is not a probability of suitability. Coarse and fine measurements from one DEM share source ancestry.

## Layout

- `src/`: terrain measurements, ranking, source quality and feature-study workflow.
- `services/api/`: FastAPI endpoints serving the research records.
- `apps/web/`: React and TypeScript explorer, bundled fonts and public evidence.
- `scripts/`: acquisition, analysis, reproduction and publication commands.
- `configs/` and `data/metadata/`: protocols, source labels and acquisition provenance.
- `artifacts/paper/` and `artifacts/reports/`: manuscript and measured records.
- `tests/`: focused scientific and API checks.

Raw observations, restricted archives, installed dependencies, planning drafts and local review material are excluded from Git. The historical discovery record is compressed losslessly; `prepare_checkout.py` restores it for analysis, while the API can read either form.

## Verify and reproduce

```sh
python -m pytest -q
npm run build
python scripts/measure_site_stability.py
```

Native downloads are required only for source-dependent scientific reconstruction. The supplied research bundle runs without downloading the original rasters.

`python scripts/run_triad_study.py --help` lists the separate freeze, selection, evaluation and challenge stages. The [input schema](configs/triad-study.schema.json) specifies the required observations. A real study still needs verified rim polygons, independent process controls and sufficient source-quality evidence before it can advance.

## Sources and credits

NASA/USGS NASADEM, MGS MOLA, LRO LOLA/LROC, HLS and EMIT supply the principal observations. Additional products include USGS/USDA NAIP and 3DEP, USGS SIM 3464, IGN terrain, ESA WorldCover and Copernicus DEM. Contains modified Copernicus data. Product identifiers, citations, acquisition details and original provider terms remain in the source manifests.

OpenStreetMap-derived records credit [OpenStreetMap contributors](https://www.openstreetmap.org/copyright) under the ODbL. Puga spectra originate from Zenodo records [3992541](https://doi.org/10.5281/zenodo.3992541) and [6304000](https://doi.org/10.5281/zenodo.6304000), CC BY 4.0. Their published study is Sarkar et al., [2022](https://doi.org/10.1029/2022JE007299).

The NASA Planetary Pits and Caves Analog Dataset is by Uland Wong, Warren Whittaker, Heather Jones and Red Whittaker, December 2014. Its original clouds and photographs remain excluded: research/academic permission does not authorize public database redistribution or commercial use. Original climate rasters are also excluded where provider terms remain unresolved.

Source Sans 3 by Adobe and Newsreader by Production Type use the SIL Open Font License; their full licenses accompany the bundled fonts. Lucide icons use ISC. Design guidance adapted from [unslop by Damir Sokolovsky](https://github.com/heydamir/unslop) is credited under CC BY 4.0.

The software is MIT licensed. Source data retain their own terms. Codex assisted with implementation, analysis and writing; independent geological review and NASA endorsement are not claimed.
