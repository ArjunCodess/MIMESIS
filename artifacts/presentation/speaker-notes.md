# Speaker notes

A roughly four-minute pitch. Speak to someone who has never worked with planetary maps. Show the website and explain what the result means before discussing how it was calculated.

## 1. MIMESIS

Before we send equipment to the Moon or Mars, we can study useful places on Earth. But a place that looks similar may still be a poor match. MIMESIS helps researchers compare land shapes, see possible Earth locations and check why those places were selected. The screenshot shows the working website. The views are made from height data, rather than ordinary photographs. Our focus is comparing broad landscapes, not certifying a landing site or a safe rover route.

## 2. How it works

We use NASA height maps for Earth, Mars and the Moon. NASADEM provides the Earth data, MOLA the Mars data and LOLA the lunar data. We compare 3,693 overlapping Earth areas in Namibia and Chile with six space targets. Each Earth area is 20 kilometres wide. We run the comparison at two map scales and with two different methods. Then we ask a simple question: does the selected place stay nearby, or does it move somewhere else? These overlapping areas are not thousands of independent sites.

## 3. Same ground

Nili Fossae is an area on Mars. When we changed map scale, none of the entries in its top-ten Earth list kept the same ID. That sounded like a completely different result. But the two winning areas were only three kilometres apart. Their shared ground was 73.9% of their combined area. Five pairs from the two top-ten lists could be matched within ten kilometres, counting each area only once. Different entries can therefore describe much of the same ground. This is partial agreement, not proof that every choice stayed stable.

## 4. Different choices

Changing the comparison method had a much larger effect in two cases. The Earth choices for Jezero and Syrtis moved between Namibia and Chile, more than 8,300 kilometres. Changing map scale within a method moved a winner by at most 24.2 kilometres. The chart keeps all six targets visible, including those that changed much less. We changed whole methods, so this does not tell us which method is better or which individual setting caused the change. It tells users to inspect the assumptions before trusting the first result.

## 5. The website

The Methods page shows how the comparisons are made. The Data page shows the NASA sources, missing coverage and files people can download. Researchers can inspect the maps and measurements themselves. We also export the selected areas in a standard map file, GeoJSON. Each entry keeps its location, source and validation status. The shortlist favours areas that rank reasonably at both scales. A shortlist is a starting point for research, not permission to visit or a claim of geological similarity.

## 6. Honest checks

We also tried comparing lunar pits. The screenshot shows one case where our quality check left no usable area for the chosen measurement. We needed 95%. The other lunar case also failed. Changing the quality-mask settings did not make either case pass, across 120 settings in total. We stopped rather than claiming that the comparison worked. Nine focused software tests pass, but code tests cannot replace geological or field checks. A separate sampling experiment also shows that changing how terrain is observed can change the measured slope; the paper records all eighteen comparisons.

## 7. Why it matters

The intended benefit is to help researchers decide which places and observations to study next, before planning fieldwork. We have built the website and released maps, measurements, code and the research paper. We also have a new result within this project: rank changes can hide shared ground, while different comparison methods can choose different continents. We have not confirmed a new geological analogue or measured savings in time, money or mission risk. The next step is to check the geology and test whether the selected places help a real exploration task. Everything is available on GitHub.

## Evidence for the judging criteria

- **Impact:** Slides 1 and 7 explain who could use the tool and the decision it supports. The benefit is proposed; measured mission savings are not claimed.
- **Creativity:** Slides 3 and 4 show the two measured findings that change how the rankings should be read. General ranking and sensitivity methods are not claimed as new inventions.
- **Validity:** Slide 6 shows a failed case and why the project stops that claim. The paper and code preserve the rules, calculations and limits.
- **Relevance:** Slide 2 identifies the NASA data actually used to compare Earth, the Moon and Mars. The software screens locations for a stated terrain task.
- **Presentation:** The seven slides follow the problem, method, finding, working tool and next step. Five supplied screenshots demonstrate the application.

## Source and claim details

The precise term for the shared-ground measure is intersection-over-union: shared area divided by combined area, not the share of either single square. The map scales are 500 metres and 1,000 metres. The methods are the four-variable scalar comparison and the multigroup score described in the paper. The new chart reports the largest displacement per target within each comparison type, using a distance axis that changes to logarithmic spacing away from zero.

The Namibia example on slide 7 is the Nili scalar compromise window centred at 25.16248 degrees south, 16.05951 degrees east. It ranks 17 and 19 at the two scales, outside both top tens. It is not an approved field location. The wider regions are established analogue environments; a previously unrecognised geological site has not been established here. Earth also does not reproduce lunar vacuum and gravity, the Martian atmosphere or their radiation environments.

