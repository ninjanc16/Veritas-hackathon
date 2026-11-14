# Rio Grande Farm Drought Outlook

**Track:** AI + Climate | **Team:** [TEAM: names and schools] | **Live app:** [TEAM: paste the app link] | **Video:** [TEAM: paste the video link]

## The problem
Drought is the normal risk along the Rio Grande, and it forces expensive choices: sell cattle or buy hay, plant or leave a field dry, apply for aid or not. The U.S. Drought Monitor shows where drought is now, but not what is likely next month, next season or next year in a given county. Our users are ranchers and irrigated-crop farmers in 31 counties in Colorado, New Mexico and Texas, plus the county Farm Service Agency offices and irrigation districts that work with them.

## What we built
- **4-week alert:** a Low, Watch or Warning level for severe drought (D2 or worse).
- **6-month outlook:** the chance of 8 straight weeks of severe drought, the trigger of a federal livestock aid program.
- **12-month outlook:** about how many weeks of severe drought to expect, next to the usual for the county and the typical error.
- **Canal action tab:** turns the 6-month forecast into a ranked list of irrigation districts and a cost estimate for sealing canals.
- **App:** [TEAM: paste the app link]

## What we added
1. **A target that matches a real farm rule:** the 6-month outlook predicts the 8-straight-weeks trigger, not a generic drought index.
2. **Longer outlooks, tested honestly:** 6 and 12 months, each against "the future equals today" and "the usual for this county".
3. **A transfer test:** a model built on the Rio Grande, tried unchanged on four other rivers. It breaks on wetter rivers, and we report that.
4. **A canal action plan triggered by the forecast:** the forecast is the only AI part. The district ranking and the cost calculator are arithmetic on published Texas A&M and Bureau of Reclamation figures, and every screen labels them estimates.

## How it works
Weekly county drought maps from the U.S. Drought Monitor, each county's neighbors and the Pacific El Nino index go in. A tier and risk score (4 weeks), a percent (6 months) and a number of weeks (12 months) come out. The models are random forests trained on Rio Grande counties only. The 4-week alert trains on 2000 to 2014, tunes on 2015 to 2018 and tests on 2019 to 2026. Each outlook test year is predicted by a model trained only on earlier years. Baselines: "the future equals today", "D1 or worse now", "getting worse", "typical for the time of year" and "usual for the county". Leakage checks: time splits, leakage tests and a shuffled-label check (average AUC 0.44).

## Results
Cost = 3 x missed droughts + false alarms. That rule is our assumption, not a farmer's number.

**4-week alert (Rio Grande, test years)**

| Rule | Cost | Precision | Recall |
|---|---|---|---|
| Our system | 1912 | 0.932 | 0.935 |
| Persistence | 2403 | 0.974 | 0.898 |
| D1 now | 2333 | 0.782 | 0.984 |
| Worsening | 1971 | 0.933 | 0.932 |

**6-month outlook:** our cost 2324 (precision 0.733, recall 0.868) against 2382 for "D1 or worse now", 3133 for persistence and 3871 for the usual. That is close to a tie with the D1 rule.

**12-month outlook:** average error 14.0 weeks, against 14.52 for "same as now", 15.18 for "same as last year" and 17.39 for the usual. It is a planning range.

**Pre-season trigger (outlooks issued January to March, 852 drought seasons)**

| Rule | Fires | Caught | False alarms | Precision | Recall |
|---|---|---|---|---|---|
| Our forecast | 1061 | 790 | 271 | 0.745 | 0.927 |
| Our forecast with reservoirs | 1032 | 771 | 261 | 0.747 | 0.905 |
| D1 or worse now | 1023 | 780 | 243 | 0.762 | 0.915 |
| D2 or worse now | 661 | 591 | 70 | 0.894 | 0.694 |
| Seal every year | 1674 | 852 | 822 | 0.509 | 1.0 |

At a cost ratio of 0.25 the forecast is worth 0.3135 per decision against 0.3132 for the D1 rule. That is a tie, not a win. Reservoir storage did not help.

**Other rivers.** The Rio Grande-trained model did not beat the best simple rule on the Mississippi, Missouri, Colorado or Ohio.

**A weak result.** For counties not yet in severe drought, our system cost 1735 against 1794 for the best simple rule (Worsening).

**A failure example.** 2023-04-04, Hidalgo, Texas: the system warned with a risk score of 1.00, but the county did not reach severe drought in the next 4 weeks.

## What we'd do next
Snowpack and river flow as inputs, the real grazing-period rule, a rancher's own cost numbers, and crop-loss data to test the link to dollars. A one-mile field test of canal sealant on a Rio Grande canal, and current irrigation-district efficiency data (the figures we use are from 1998).

## Sources
- Drought data: U.S. Drought Monitor (NDMC, USDA, NOAA), https://droughtmonitor.unl.edu ; county archive by the Montana Climate Office
- ENSO index: NOAA Climate Prediction Center, https://www.cpc.ncep.noaa.gov
- River lines: Natural Earth (public domain), https://www.naturalearthdata.com ; map: OpenStreetMap contributors, CARTO
- Canal lines: U.S. Geological Survey, National Hydrography Dataset, https://www.usgs.gov/national-hydrography ; soils: USDA NRCS Soil Survey (SSURGO)
- Reservoir storage: Texas Water Development Board, https://waterdatafortexas.org
- Insured drought losses: USDA Risk Management Agency, Cause of Loss files
- District efficiency and seepage rates: Texas A&M (Fipps), 1998, https://gfipps.tamu.edu/files/2019/12/RGV-Potential-Water-Savings.pdf
- Sealant price, yearly reapplication, lining price: U.S. Bureau of Reclamation, https://www.usbr.gov/research/projects/detail.cfm?id=845
- Sealant field results: Desert Research Institute, https://www.researchgate.net/publication/270766967_Field_Demonstration_of_Polyacrylamide_in_an_Unlined_Irrigation_Canal ; Lund et al. 2021, https://www.sciencedirect.com/science/article/abs/pii/S0378377421001633
- Pipe cost and canal losses: Associated Press, 2021, https://www.ksat.com/news/politics/2021/10/16/in-south-texas-aging-water-system-meets-growing-population/
- Fallowing prices: https://abqstew.com/2022/04/11/the-cost-of-drought-why-some-farmers-wont-be-planting-this-season/ and https://www.fws.gov/project/water-leasing-middle-rio-grande-valley
- Valley program ($164 million, 44,000 acre-feet, 12 districts): https://smartwatermagazine.com/news/smart-water-magazine/nadbank-backs-164-million-water-conservation-push-in-texas-and-mexico
- App libraries: pandas https://pandas.pydata.org , pyarrow https://arrow.apache.org/docs/python , Streamlit https://streamlit.io , Plotly https://plotly.com/python , pytest https://pytest.org
- Modeling libraries: [TEAM: Pipeline owner to list]
- AI tools used, and what for: [TEAM: list every AI tool and what it was used for, as the hackathon rules require]

---

# Appendix

## Run the app
```bash
pip install -r requirements-app.txt
python app/make_demo_data.py     # fake demo files (the app uses real files when they exist and are valid)
pytest tests/app -q
streamlit run app/streamlit_app.py
python app/export_pitch_kit.py   # numbers, write-up draft and charts for the video
```
For the pipeline commands see `ARCHITECTURE_PIPELINE.md`.

## What this tool must not claim
1. It does not decide, predict or guarantee any USDA payment. Ask your county FSA office.
2. It is not financial or legal advice.
3. It does not tell anyone how to allocate water. Western water rights and interstate compacts decide that.
4. It does not predict crop yields, and we did not measure any dollars saved.
5. It was trained on 31 Rio Grande counties. On other rivers it is a test, not a product.
6. The 12-month outlook is a planning range. Always show its typical error next to it.
7. The 4-week risk score is not a calibrated probability.
8. The cost rule (one miss equals three false alarms) is our assumption, not a farmer's number.
9. State each weak result exactly as `metrics.json` reports it: onset, the 6-month margin over the "D1 or worse now" rule, and the rivers where the model failed.

For the canal action tab:
1. The forecast is tested. The canal plan is a proposal built from published figures.
2. For this decision, state how the forecast compared with the simple "D1 or worse now" rule, exactly as `metrics.json` reports it.
3. The sealant has not been field-tested on the Rio Grande. Results elsewhere ranged from no effect to a full stop of seepage.
4. District figures are from 1998. Some canals have been lined since.
5. Valley canals also carry city water. Any sealant would need the district's and regulators' approval.

Never claim a number of acre-feet or dollars saved on the Rio Grande.

## Limits (every sentence from `reports/metrics.json`)
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
