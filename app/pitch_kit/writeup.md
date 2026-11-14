STATUS: DEMO DATA - DO NOT USE

# Rio Grande Farm Drought Outlook

**Track:** AI + Climate  |  **Team:** [TEAM: names and schools - no emails in the repo]

## The problem
Along the Rio Grande, drought is the normal risk, and it forces expensive decisions: sell cattle or
buy hay, plant or leave a field fallow, file for disaster aid or not. Farmers get a weekly map of
where drought is now (the U.S. Drought Monitor), but not a county-level answer to "what is likely here
next month, next season and next year?" Our users are ranchers and irrigated-crop farmers in
12 counties in Colorado, New Mexico and Texas, and the county Farm Service Agency
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
- **Model:** random forests trained on Rio Grande counties only (DEMO).
- **Time split:** the 4-week alert trained on 2000 to 2014, tuned on
  2015 to 2018, tested on 2019 to 2026. Each
  outlook test year is predicted by a model trained only on earlier years.
- **Baselines:** "the future equals today", "D1 or worse now", "getting worse", "typical for the time
  of year", and "usual for the county".
- **Leakage checks:** time splits, leakage tests, and a shuffled-label check (average AUC
  0.5).

## Results
Cost = 3 x missed droughts + false alarms. That cost rule is our assumption, not a farmer's number.

**4-week alert, Rio Grande test years.** Honesty check (beats every simple rule): passed.

| Rule | Cost | Precision | Recall |
|---|---|---|---|
| Our system | 603 | 0.864 | 0.993 |
| Persistence (D2 or worse now) | 4119 | 0.913 | 0.619 |
| D1 or worse now | 1649 | 0.782 | 0.926 |
| Worsening | 3771 | 0.862 | 0.669 |
| Typical for the time of year | 1412 | 0.708 | 1.0 |

**6-month outlook.** Beats every baseline: yes.

| Rule | Cost | Precision | Recall |
|---|---|---|---|
| Our system | 600 | 0.691 | 0.995 |
| Persistence (D2 or worse now) | 2123 | - | - |
| D1 or worse now | 1428 | - | - |
| Usual for the county | 1240 | - | - |

**12-month outlook.** Beats every baseline: yes.

| Rule | Average error (weeks) |
|---|---|
| Our system | 5.5 |
| Same as now | 23.8 |
| Same as last year | 10.8 |
| Usual for the county | 6.7 |

**Other rivers.** The model was trained on the Rio Grande only:

| River | Our cost | Best simple rule | Its cost |
|---|---|---|---|
| Colorado | 272 | D1 now | 769 |
| Rio Grande | 603 | D1 now | 1649 |
| Mississippi | 431 | D1 now | 1013 |
| Ohio | 187 | Persistence | 175 |
| Missouri | 402 | D1 now | 982 |

**A weak result.** On counties not yet in severe drought (the hard part), our system cost
300 against 310 for the best simple rule (D1 now).

**A failure example.** 2019-01-15, Demo County RI3, Texas (4-week alert): DEMO: the system stayed quiet but severe drought arrived within 4 weeks.

**What the results do not show:**
- DEMO DATA - these are not real results

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
