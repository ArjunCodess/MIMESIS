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

The original lunar pit pilot fails its declared source-support checks. A later replication reproduces seven published terrain-ranking sensitivity calculations from processed feature records. An independent adaptation on 3,693 MIMESIS Earth windows changes the leading window for four of six targets when derivative support changes. These are exploratory results; no new geological analogue or permanent-base location has been established.

Scientific records retain source identities, hashes, masks and exclusions. Missing terrain is not treated as smooth ground, and a ranking is not a probability of suitability. Coarse and fine measurements from one DEM share source ancestry.

## Layout

- `src/`: terrain measurements, ranking, source quality and feature-study workflow.
- `services/api/`: FastAPI endpoints serving the research records.
- `apps/web/`: React and TypeScript explorer, bundled fonts and public evidence.
- `scripts/`: acquisition, analysis, reproduction and publication commands.
- `configs/` and `data/metadata/`: protocols, source labels and acquisition provenance.
- `artifacts/paper/` and `artifacts/reports/`: manuscript and measured records.
- `tests/`: focused scientific, API and browser checks.

Raw observations, restricted archives, installed dependencies, planning drafts and local review material are excluded from Git. The historical discovery record is compressed losslessly; `prepare_checkout.py` restores it for analysis, while the API can read either form.

## Verify and reproduce

```sh
python -m pytest -q
npm run build
npx playwright install chromium
npx playwright test --workers=2
python scripts/audit_github_readiness.py
```

The native downloads are required only for source-dependent scientific reconstruction. To reproduce the attributed ranking comparison and apply the baseline to the supplied MIMESIS measurements:

```sh
python scripts/acquire_comparison_sources.py
python scripts/run_comparison_tests.py
python scripts/replay_terrain_comparison.py
python scripts/compare_scalar_baseline_v11.py
python scripts/publish_replication_v11.py
```

`python scripts/run_triad_study.py --help` lists the separate freeze, selection, evaluation and challenge stages. The [input schema](configs/triad-study.schema.json) specifies the required observations. A real study still needs verified rim polygons, independent process controls and sufficient source-quality evidence before it can advance.

## Sources and credits

NASA/USGS NASADEM, MGS MOLA, LRO LOLA/LROC, HLS and EMIT supply the principal observations. Additional products include USGS/USDA NAIP and 3DEP, USGS SIM 3464, IGN terrain, ESA WorldCover and Copernicus DEM. Contains modified Copernicus data. Product identifiers, citations, acquisition details and original provider terms remain in the source manifests.

OpenStreetMap-derived records credit [OpenStreetMap contributors](https://www.openstreetmap.org/copyright) under the ODbL. Puga spectra originate from Zenodo records [3992541](https://doi.org/10.5281/zenodo.3992541) and [6304000](https://doi.org/10.5281/zenodo.6304000), CC BY 4.0. Their published study is Sarkar et al., [2022](https://doi.org/10.1029/2022JE007299).

The NASA Planetary Pits and Caves Analog Dataset is by Uland Wong, Warren Whittaker, Heather Jones and Red Whittaker, December 2014. Its original clouds and photographs remain excluded: research/academic permission does not authorize public database redistribution or commercial use. Original climate rasters are also excluded where provider terms remain unresolved.

The replication credits [Terrestrial Analog Finder](https://github.com/shishir-kuet/terrestrial-analog-finder) and [Analog Atlas](https://github.com/end13s/analog-atlas). Exact inspected commits and reproduction boundaries are retained in the records; third-party source snapshots are not redistributed. The scalar adaptation is independently implemented.

Source Sans 3 by Adobe and Newsreader by Production Type use the SIL Open Font License; their full licenses accompany the bundled fonts. Lucide icons use ISC. Design guidance adapted from [unslop by Damir Sokolovsky](https://github.com/heydamir/unslop) is credited under CC BY 4.0.

The software is MIT licensed. Source data retain their own terms. Codex assisted with implementation, analysis and writing; independent geological review and NASA endorsement are not claimed.
