STATUS: PROVISIONAL - DO NOT USE IN THE FINAL VIDEO OR WRITE-UP

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
- Provisional: river flow not tested yet.
- The cost rule (a miss costs 3 false alarms) is our assumption.
- The 4-week risk score is not a calibrated probability.
- On the Rio Grande the 4-week system (cost 1912) is close to a tie with the best simple rule, Worsening (cost 1971).
- On the other four rivers the Rio Grande-trained 4-week system beats persistence on the Mississippi, Missouri and Colorado, but it does not beat the best simple rule on any of them.
- The 6-month outlook (cost 2324) is close to a tie with the 'D1 or worse now' rule (cost 2382). It fails on the Mississippi, Missouri and Ohio.
- The 12-month outlook is off by 14.0 weeks on average, against an average of 22.1 weeks. It is a planning range, not a precise forecast.
- The 31 Rio Grande counties move together, so the real sample is about 18 years, not thousands of rows.
- Design choices were made after exploratory runs on the same test years.

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
