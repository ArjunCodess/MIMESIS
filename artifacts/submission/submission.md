# MIMESIS

**Challenge:** Identify Earth Locations that Analog the Permanent Moon Base Locations and Mars

**Author:** Arjun Vijay Prakash, Grade XI, City Montessori School, Kanpur Road, Lucknow, India

**Event:** Lucknow local event, NASA Space Apps 2026

**Project:** https://github.com/ArjunCodess/MIMESIS

## Summary

MIMESIS helps researchers find Earth landscapes that could support preparation for Moon and Mars exploration. It brings NASA height maps, terrain comparisons, source records and downloadable locations into one working website.

Users select a planetary target, explore possible Earth matches and inspect the measurements behind each result. We compared 3,693 overlapping Earth areas in Namibia and Chile with six locations on the Moon and Mars, using NASADEM, MOLA and LOLA data.

Our study found that a changed ranking does not always mean a different landscape. For Nili Fossae, two winning Earth areas were only three kilometres apart, despite completely different top ten lists. Changing the comparison method had a larger effect: choices for Jezero and Syrtis moved between Namibia and Chile, more than 8,300 kilometres.

MIMESIS makes these differences visible, helping users understand how assumptions affect the places selected. The project includes an interactive explorer, geographic exports, reproducible analysis, a research paper and an editable presentation.

Its intended benefit is to guide further investigation before fieldwork. We report missing data and failed quality checks openly. The results identify research candidates, not verified geological analogues or safe base locations. Independent geological checks and exploration tests remain necessary before making stronger claims.

## Project details

Users choose a Moon or Mars target, inspect possible Earth matches and review the measurements behind each result. MIMESIS compares height changes, slopes, roughness and surrounding terrain. NASADEM supplies Earth height data, MOLA supplies Mars data and LOLA supplies Moon data.

The study covers 3,693 overlapping areas in the Namib and Atacama, compared with six planetary targets. We tested two map scales and two comparison methods. For Nili Fossae, none of the top-ten entries kept the same ID across scales, but the winning areas were only three kilometres apart and overlapped substantially. For Jezero and Syrtis, changing the comparison method moved the selected area between Namibia and Chile, more than 8,300 kilometres.

Our contribution is showing how a changed ranking can mean either nearby shared ground or a very different location. The website lets users inspect that distinction instead of relying on one score.

We built the analysis in Python using NumPy, SciPy, Rasterio and PyProj. The website uses React and TypeScript, with a FastAPI backend. The paper and presentation use LaTeX. The release includes source records, geographic exports, nine focused software tests and instructions for reproducing the calculations.

We considered map scale, missing observations, data quality, overlapping areas and differences between Earth and space environments. Failed lunar quality checks remain visible rather than being hidden. The intended benefit is to help researchers choose places and observations for further study. We have not confirmed a new geological analogue, proven field usefulness or established that any location is suitable for a permanent base.

## Evidence for the five judging criteria

| Criterion | What the project delivers | What the evidence does not establish |
| --- | --- | --- |
| Impact | A desk-study tool for deciding which candidate areas and observations to investigate next, with geographic exports that can enter a GIS workflow. | Mission savings, improved training and safer landings have not been measured. |
| Creativity | A comparison that separates changed identifiers from changed ground, then exposes continent-scale disagreement between scoring contracts. | General sensitivity analysis, matching and minimax ranking are established methods; literature priority is not claimed. |
| Validity | Explicit scoring contracts, one-to-one geographic matching, source hashes, numerical controls, a reproducible analysis and retained failed cases. | Overlapping windows are not independent sites; two scales do not supply geological validation. |
| Relevance | NASADEM, MOLA and LOLA drive the measured Earth–Mars–Moon comparison. LROC and actual MOLA point-pattern diagnostics expose limits in the source data. | Terrain agreement cannot reproduce gravity, atmosphere, radiation, mineralogy or lunar polar illumination. |
| Presentation | An explorer, evidence figures, a ten-page LaTeX paper, a two-page brief, location GeoJSON and the demonstration sequence below. | No completed event submission, field test or independent review is claimed. |

## Demonstration, about 90 seconds

**0–15 seconds.** Open Explore. “We need Earth environments that help us prepare for lunar and Martian exploration. MIMESIS compares measured terrain, then asks whether the location survives a change in assumptions.” Select a target and show its Earth footprint and source-linked measurements.

**15–40 seconds.** Open Evidence → Locations and select Nili Fossae. “Here, every top-ten identifier changes between 500 m and 1,000 m support. But the winning windows move only 3 km, and their footprints have 74% intersection-over-union. Different ranks can still describe much of the same ground.” Show the exact-overlap and geographic-matching counts.

**40–60 seconds.** Select Jezero. “Changing the scoring contract moves this winner from Namibia to Chile, over 8,300 km. In these inspected cases, a stable ranking at two scales can hide a much larger dependence on how similarity is defined.” Open the target's two shortlist entries.

**60–75 seconds.** Download locations. “We export candidate footprints and source identities, with validation status attached. These are research shortlists, not claims that Chile reproduces lunar vacuum or that a low score makes a safe base.”

**75–90 seconds.** Open Pit study, then the paper. “We also retain failed source checks. Our contribution is a working tool and a reproducible geographic finding. The next scientific step is independent geological and task-specific validation of the candidate areas.”

## Deliverables

- [Research paper](../paper/mimesis-paper.pdf) and [LaTeX source](../paper/mimesis-paper.tex), with the supplied Overleaf style.
- [Two-page project brief](mimesis-brief.pdf) for judges and presentation preparation.
- [Seven-slide Beamer pitch](../presentation/mimesis-pitch.pdf), with [editable source](../presentation/mimesis-pitch.tex), actual application screenshots and [speaker notes](../presentation/speaker-notes.md).
- [Measured geographic record](../reports/site_stability.json), including contracts, source and implementation hashes, every target and matching-radius sensitivities.
- [Location GeoJSON](../../apps/web/public/research/site-shortlist.geojson), containing twelve target–contract relationships and their validation limits. Repeated windows are not independent sites.
- [Application and reproduction instructions](../../README.md).

## Data, authorship and next evidence

The new analysis needs no additional downloads: it reproduces from the bundled descriptors. Its raw observation ancestry remains in the source manifests. Supporting cave and spectral branches retain their own acquisition and permission limits; they are not evidence for a new geological discovery.

A geological follow-up needs registered process-relevant reference zones, source-quality evidence and independently assessed outcomes for a specific exploration task. The feature-scale cave study additionally needs verified rims, ground-quality metadata, survey registration and documented lunar confidence codes. Those unfinished requirements are stated in the paper rather than replaced with synthetic evidence.

Arjun Vijay Prakash built MIMESIS. Codex assisted with implementation, analysis code and writing. Required source terms, template licenses, method provenance and research citations are retained. NASA endorsement and independent expert review are not claimed.
