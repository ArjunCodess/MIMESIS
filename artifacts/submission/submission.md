# MIMESIS

**Challenge:** Identify Earth Locations that Analog the Permanent Moon Base Locations and Mars  
**Author:** Arjun Vijay Prakash, Grade XI, City Montessori School, Kanpur Road, Lucknow, India  
**Event:** Lucknow local event, NASA Space Apps 2026  
**Project:** https://github.com/ArjunCodess/MIMESIS

## Summary

Which Earth landscape should a mission team study before exploring the Moon or Mars? MIMESIS compares measured terrain and shows when the answer depends on the analysis itself. Its four-view explorer connects NASADEM Earth observations with MOLA Mars and LOLA Moon measurements, source records and downloadable locations.

The new geographic analysis uses 3,693 overlapping windows in the Namib and Atacama, six planetary targets, two scoring contracts and two spatial supports. For Nili Fossae, changing support replaces every top-ten candidate identifier, yet the winning footprints still have 73.9% intersection-over-union and their centers move only 3 km. Changing the scoring contract has a different consequence: Jezero and Syrtis winners move between Namibia and Chile, more than 8,300 km.

MIMESIS turns that distinction into a practical research tool. Users can inspect geographic continuity, compare assumptions and download target-specific terrain shortlists chosen to avoid relying on one support. Each exported entry includes a footprint, source identity and explicit validation status. These are candidate areas for follow-up, not approved field sites or permanent-base recommendations.

The contribution is a reproducible project-level finding about analogue selection. It does not establish a previously unknown geological analogue or world-first method. Geological relevance, source accuracy, access and exploration utility still require independent evidence.

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
