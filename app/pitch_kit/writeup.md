STATUS: FINAL

# Rio Grande Farm Drought Outlook

**Track:** AI + Climate  |  **Team:** [TEAM: names and schools - no emails in the repo]

## The problem
Along the Rio Grande, drought is the normal risk, and it forces expensive decisions: sell cattle or
buy hay, plant or leave a field fallow, file for disaster aid or not. Farmers get a weekly map of
where drought is now (the U.S. Drought Monitor), but not a county-level answer to "what is likely here
next month, next season and next year?" Our users are ranchers and irrigated-crop farmers in
31 counties in Colorado, New Mexico and Texas, and the county Farm Service Agency
offices and irrigation districts that work with them. [TEAM: name one real irrigation district after
checking it.]

## What we built
- **4-week alert:** a Low, Watch or Warning tier for severe drought (D2 or worse) in the next 4 weeks.
- **6-month outlook:** the chance that a county hits 8 straight weeks of severe drought in the next 6
  months, the trigger used by a federal livestock aid program.
- **12-month outlook:** about how many weeks of severe drought to expect in the next year, shown next
  to what is usual for the county and its typical error.
- **App:** [TEAM: paste the live app link here]

## What we added
1. **A target that matches a real farm rule:** the 6-month outlook predicts the 8-straight-weeks trigger
   used by a federal aid program, not a generic drought index.
2. **Longer outlooks, tested honestly:** 6 and 12 months, each against "the future equals today" and
   "the usual for this county".
3. **A transfer test:** a model built on the Rio Grande, tried unchanged on four other rivers.
   It carries over in some places and breaks in others. That is a finding, not something to hide.

## How it works
- **Goes in:** weekly county drought maps from the U.S. Drought Monitor, the county's neighbors, and the
  Pacific El Nino index. [TEAM: Pipeline owner to confirm the exact inputs.]
- **Comes out:** a tier and risk score (4 weeks), a percent (6 months) and a number of weeks (12 months).
- **Model:** random forests trained on Rio Grande counties only.
- **Time split:** the 4-week alert trained on 2000 to 2014, tuned on
  2015 to 2018, tested on 2019 to 2026. Each
  outlook test year is predicted by a model trained only on earlier years.
- **Baselines:** "the future equals today", "D1 or worse now", "getting worse", "typical for the time
  of year", and "usual for the county".
- **Leakage checks:** time splits, leakage tests, and a shuffled-label check (average AUC
  0.44).

## Results
Cost = 3 x missed droughts + false alarms. That cost rule is our assumption, not a farmer's number.

**4-week alert, Rio Grande test years.** Honesty check (beats every simple rule): passed.

| Rule | Cost | Precision | Recall |
|---|---|---|---|
| Our system | 1912 | 0.932 | 0.935 |
| Persistence | 2403 | 0.974 | 0.898 |
| D1 now | 2333 | 0.782 | 0.984 |
| Worsening | 1971 | 0.933 | 0.932 |
| Calendar | 21735 | 0.0 | 0.0 |

**6-month outlook.** Beats every baseline: yes.

| Rule | Cost | Precision | Recall |
|---|---|---|---|
| Our system | 2324 | 0.733 | 0.868 |
| Persistence (D2 or worse now) | 3133 | - | - |
| D1 or worse now | 2382 | - | - |
| Usual for the county | 3871 | - | - |

**12-month outlook.** Beats every baseline: yes.

| Rule | Average error (weeks) |
|---|---|
| Our system | 14.0 |
| Same as now | 14.52 |
| Same as last year | 15.18 |
| Usual for the county | 17.39 |

**Other rivers.** The model was trained on the Rio Grande only:

| River | Our cost | Best simple rule | Its cost |
|---|---|---|---|
| Rio Grande | 1912 | Worsening | 1971 |
| Mississippi | 9232 | Worsening | 8677 |
| Missouri | 5455 | Worsening | 5358 |
| Colorado | 572 | Worsening | 512 |
| Ohio | 4592 | Persistence | 4470 |

**A weak result.** On counties not yet in severe drought (the hard part), our system cost
1735 against 1794 for the best simple rule (Worsening).

**A failure example.** 2023-04-04, Hidalgo, Texas (4-week alert): False alarm: the system warned with a risk score of 1.00, but the county did not reach severe drought in the next 4 weeks.

**What the results do not show:**
- The cost rule (a miss costs 3 false alarms) is our assumption. Results at other costs are in cost_sensitivity.
- The 4-week risk score is not a calibrated probability.
- On the Rio Grande the 4-week system (cost 1912) is close to a tie with the best simple rule, Worsening (cost 1971).
- Onset is the hard part. For counties not yet in severe drought, the system caught 36% of the weeks that led to it, with precision 46%. Its cost was 1735, against 1794 for the best simple rule (Worsening) and 2226 for never warning.
- The 6-month outlook costs 2324, against 2382 for the 'D1 or worse now' rule. That is close to a tie.
- The 12-month outlook is off by 14.0 weeks on average, against an average of 22.1 weeks. It is a planning range, not a precise forecast.
- Transfer of the Rio Grande-trained 4-week system: it did not beat the best simple rule on: Mississippi, Missouri, Colorado, Ohio. It did not beat persistence on: Ohio.
- Transfer of the Rio Grande-trained 6-month outlook: it did not beat the best simple rule on: Mississippi, Missouri, Colorado, Ohio.
- Transfer of the Rio Grande-trained 12-month outlook: it did not beat the best baseline on: Mississippi, Missouri, Colorado, Ohio.
- The 31 Rio Grande counties move together, so the real sample is about 18 years, not thousands of rows.
- Design choices were made after exploratory runs on the same test years.
- Counties are chosen by a 50 km rule from the river's main line. A different width gives a different set.
- The Drought Monitor map is drawn by people each week, so the target includes their judgment.
- A warning is not a payment decision. The grazing-period rule of the aid program is not modeled.
- The 6-month target (8 weeks in a row at D2) matches the aid rule for years up to 2025. For 2026 USDA lowered the trigger to 4 weeks in a row (FSA Notice LFP-8).
- The damage figure on the map is an estimate, not a tested forecast. It assumes every week of severe drought is a week of bought feed, priced at USDA's 2026 monthly feed cost for an adult beef cow. It was not checked against real losses, and it inherits the 12-month outlook's error.
- Nothing here measures crop yields.
- River flow and snowpack were tested as extra inputs and are not part of the system. See ablations. The El Paso gauge had no daily flow data and was dropped. The Del Norte gauge ends in 2024.
- Weather inputs (rain, temperature, soil moisture) were not tested.
- A random forest cannot predict a drought longer or deeper than any it saw in training.
- Seed check: retrained with 10 random seeds, the system beat the best simple rule in 8/10 runs for the 4-week alert, 3/10 for the 6-month outlook and 10/10 for the 12-month outlook.
- Buffer check: with a 100 km county rule (53 counties), the 4-week system cost 3269 against 3243 for the best simple rule (Worsening).
- An outside review suggested two simple rules that were not in our baseline list. They were scored after the final run. 4-week rule 'D2 now, or D1 and worse than 4 or 8 weeks ago': cost 1840 on the test years, against 1912 for the system. 12-month rule 'average of 'same as now' and 'same as the last 52 weeks'': average error 13.21 weeks, against 14.0 for the system.
- The 6-month outlook uses an El Nino value that NOAA publishes a few days into the month, around the same days the outlook is issued. A real-time forecast might have to use the value from a month earlier.
- Pre-season trigger (outlooks issued January to March): our forecast caught 790 of 852 drought seasons with 271 false alarms. The simple rule 'D1 or worse now' caught 780 with 243. At a cost ratio of 0.25 the forecast is worth 0.3135 per decision against 0.3132 for the rule. That is a tie, not a win.
- Reservoir storage did not help. The 6-month outlook costs 2452 with reservoir inputs, against 2324 without them. As a pre-season trigger the reservoir forecast caught 771 drought seasons with 261 false alarms.
- Only 14 of the 31 Rio Grande counties are matched to a reservoir, and that matching is our assumption.
- County drought is not the same as water supply. Water in the canals also depends on reservoir releases and on Mexico's deliveries under the 1944 water treaty, which are not modeled.
- The loss figures are insured crop losses only, not all drought losses, and are not adjusted for inflation.
- The canal map shows where canals and ditches are. It does not say which are irrigation canals, which are lined, how much any canal leaks or which district owns it.
- The canal priority levels are an estimate of where leaks are likely, not measured leaks. They combine the 6-month forecast with a published seepage rate for the soil under each canal. They assume bare-earth canals, because we do not know which canals are lined. No canal was inspected or measured by us.

## What we'd do next
Snowpack and river flow as inputs, the real grazing-period rule, a rancher's own cost numbers, and
crop-loss data to test the link to dollars.

## Sources
- Drought data: U.S. Drought Monitor (NDMC, USDA, NOAA), https://droughtmonitor.unl.edu ; county archive by
  the Montana Climate Office [TEAM: add link]
- ENSO index: NOAA Climate Prediction Center, https://www.cpc.ncep.noaa.gov
- App libraries: pandas https://pandas.pydata.org , pyarrow https://arrow.apache.org/docs/python ,
  Streamlit https://streamlit.io , Plotly https://plotly.com/python , pytest https://pytest.org
- Modeling libraries: [TEAM: Pipeline owner to list]
- AI tools used, and what for: [TEAM: the hackathon rules require every AI tool to be credited - list them here]
