STATUS: PROVISIONAL - DO NOT USE IN THE FINAL VIDEO OR WRITE-UP

# Explain sheet
Everyone on the team reads this before recording the video.

## 1. What is the U.S. Drought Monitor, and what do D0 to D4 mean?
A map drawn every week by experts at NDMC, USDA and NOAA that shows how dry each place is. The classes go from D0 (abnormally dry) through D1 (moderate), D2 (severe) and D3 (extreme) to D4 (exceptional). We forecast their map, not the weather itself.

## 2. What exactly does each of the three products predict?
The 4-week alert says whether a county is likely to reach D2 or worse within 4 weeks (Low, Watch or Warning). The 6-month outlook gives the chance of 8 straight weeks at D2 or worse in the next 26 weeks. The 12-month outlook estimates how many of the next 52 weeks will be at D2 or worse.

## 3. What is a random forest, in plain words? Why use it here?
It is a crowd of many small decision trees. Each tree sees a slightly different random slice of the data, and their answers are combined by voting or averaging. It needs little tuning, copes with inputs on different scales, and is hard to overfit. That suits a small, noisy dataset.

## 4. What goes into the model? What does 'neighbors within 150 km' mean?
The county's own recent drought history, the drought in nearby counties, the Pacific El Nino index and the time of year. 'Neighbors within 150 km' means we average the drought class of counties whose centers are within 150 km, because drought moves across borders. [TEAM: Pipeline owner to confirm the exact inputs and the 150 km figure.]

## 5. Why split by time, and not at random?
The real job is predicting the future. Drought weeks next to each other look almost identical, so a random split lets the model peek at the answer through a neighboring week and the score looks better than it is. A time split trains on the past and tests on years it never saw.

## 6. What is leakage, and how did we check for it?
Leakage is when information from the future sneaks into training. We guard against it with time-based splits, automated leakage tests, and a shuffled-label check: with the answers scrambled, the model's AUC should be near 0.5. Ours was 0.44.

## 7. What is the persistence baseline? What is climatology?
Persistence is 'the future equals today': warn if the county is in severe drought right now. Climatology is 'the usual for this county': what normally happens, ignoring today. A forecast is only useful if it beats both.

## 8. What are precision and recall, and why not report accuracy?
Precision: of the warnings we gave, how many were followed by severe drought. Recall: of the real droughts, how many we warned about. Accuracy can look great while being useless, for example a system that never warns scores well in a place where drought is rare.

## 9. Where does 'a miss costs 3 false alarms' come from, and why does that give a 0.25 threshold?
It is our assumption (miss cost = 3), not a farmer's number. If a miss is 3 times worse than a false alarm, it pays to warn whenever the chance is at least 1 divided by (1 + 3). The 6-month threshold in metrics.json is 0.25.

## 10. Why does the 12-month outlook predict a number of weeks, and not yes or no?
A yes-or-no warning a year ahead is nearly always 'yes' on the Rio Grande, so 'always warn' beats any model. A number of weeks is something a rancher can plan around. It is a planning range, not a precise forecast: the typical error is about 14.0 weeks, on an average of 22.1 weeks.

## 11. Why does the Rio Grande model fail on the Ohio?
The model learned a place where drought is the norm. On the Ohio severe drought is rare, so what it learned does not carry over. On the Ohio our system cost 4592 against 4470 for the best simple rule (Persistence).

## 12. What are the three weakest points of this project?
1) Onset: for counties not yet in severe drought our system cost 1735 against 1794 for the best simple rule (Worsening). 2) The 6-month margin: our cost 2324 against 2382 for the 'D1 or worse now' rule, so much of the skill is persistence. 3) Small sample: the 31 Rio Grande counties move together, so the real sample is far smaller than the row count.

## 13. Which parts did AI tools write, and how did we check them?
[TEAM: write this yourselves, honestly - which AI tools were used for what, and how each part was checked (tests, reading the code, comparing with the numbers in metrics.json).]
