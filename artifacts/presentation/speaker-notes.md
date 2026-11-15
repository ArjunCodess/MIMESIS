# Speaker notes

The seven slides support a roughly five-minute pitch. The 90-second software-only demonstration is in `artifacts/submission/submission.md`. Keep the distinction between a working application, a measured geographic result and independent geological validation throughout.

## 1. Challenge and working solution

MIMESIS asks which Earth terrain could help prepare a particular mapping exercise for the Moon or Mars. The screenshot shows the real Explore workspace comparing a planetary reference with NASADEM Earth terrain and ranked footprints. These views are derived from elevation, not color photographs. The application allows target selection, support changes, candidate inspection and evidence export. We focus on regional terrain mapping; a 500 m grid cannot certify individual rover obstacles or construction safety. Introduce yourself as Arjun Vijay Prakash, a Grade XI student from City Montessori School, Kanpur Road, Lucknow.

## 2. Data and method

NASA observations supply the actual measurements, rather than decoration. There are four Martian targets from MOLA, two lunar targets from LOLA and 3,693 Earth windows derived from NASADEM in two bounded regions. Each 20 km window is embedded in 80 km context. The 3 km spacing means that neighboring windows share much of their ground. Explain both contracts as whole definitions of similarity. The multigroup score already includes alternate support among its 35 scenarios, so its lower support sensitivity is partly expected by design. Neither score is a probability of relevance.

## 3. Nili result and Evidence demo

Start with what initially looked like complete instability: none of Nili's scalar top-ten candidate IDs survives the support change. The geographic follow-up changes that interpretation. The winning centers move 3 km and their intersection-over-union is 73.91%. That is intersection divided by union, not the fraction of either one window retained. Maximum-cardinality one-to-one matching finds five top-ten pairs within 10 km and seven within 40 km. We report the whole radius sensitivity rather than treating 10 km as a validated equivalence threshold. Nili's minimax choice ranks 17 and 19, which also means the compromise is weak.

## 4. Contract-dependent location choice

The largest support displacement within either contract is 24.19 km. At fixed support, changing the scoring contract sends Jezero from Namib to Atacama and Syrtis in the other direction, over 8,300 km. Nili remains in Namibia but shifts about 72–75 km. Isidis and Shackleton differ by much less; Taurus-Littrow agrees exactly. Retaining all six cases avoids telling the story only through the two dramatic examples. The contracts differ in observables, normalization, weights and aggregation. This is not a controlled test of one ingredient, nor proof that our preferred score is more scientifically accurate.

## 5. Methods, sources and exports

The screenshots show the actual Methods and Data pages. The method and source records are meant to let another researcher inspect the assumptions and locate missing evidence. The new GeoJSON has twelve target–contract entries, including repeated physical windows where different targets share a choice. Do not describe those as twelve independently discovered sites. Each choice minimizes the worse rank across supports, with rank sum and candidate ID as deterministic tie-breakers. The JSON retains bundle and implementation hashes. Running the new analysis reproduces calculations from frozen descriptors; reconstructing the original DEM measurements is a separate workflow.

## 6. Validity and failed cases

The lunar pit screenshot shows why we stop some claims rather than force an attractive analogue. Tranquillitatis and Marius Hills fail the declared neighborhood-support requirement. Six analytical-plane controls pass, but all 120 acquired-mask sensitivities fail. This is a source-support result, not evidence that caves are physically dissimilar. The separate eighteen MOLA-pattern transfers lower median slope under linear reconstruction; geometry and reconstruction change together. Missing original quality fields prevent a stronger accuracy claim. Nine focused tests cover physical behavior, evidence boundaries, geography and API integration. Passing software tests is not field validation.

## 7. Contribution, delivery and next evidence

State the contribution once: MIMESIS exposes the difference between changing a rank, changing the ground and changing the scoring assumptions. The application, measured results, geographic exports, paper, brief and editable deck are available on GitHub. The Nili coordinate is an analysis-window center, not a surveyed feature or approved field destination. The next scientific step is independent process-relevant reference zones, qualified observations and outcomes for a declared mapping task. Earth does not reproduce lunar vacuum or gravity, Martian atmospheric conditions, radiation or polar illumination. We have an original project-level geographic result, not a newly validated geological analogue. Codex assistance and required research provenance remain disclosed in the project.
