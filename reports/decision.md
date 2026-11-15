# Decision record: choices fixed before the final run

**Written:** Saturday Nov 14, 2026, 7:20 AM PT. Committed before the final run that writes `metrics.json` with `is_final: true`.

## What this file is for

It lists every choice that could change the results, fixed in writing before the final numbers are produced. After this commit, nothing below is changed, whatever the final run shows.

## An honest statement about what we had already seen

These choices were **not** made blind. The design was chosen after exploratory runs on the same test years (the scripts in `notebooks/`), and provisional runs of this code had already shown test-year results. So the test years are not a perfectly untouched sample. What we can say is:

- No setting was changed after seeing a test-year result from this code.
- The 4-week alarm threshold was picked on validation years only (a test proves it never sees test rows).
- The outlook threshold of 0.25 follows from the cost rule. It was not tuned.

## Fixed choices

**Scope.** Rio Grande counties: a county is in if its center is within 50 km of the river (31 counties). Models are trained on these counties only. The Colorado, Missouri, Mississippi and Ohio are a transfer test.

**Target.** Severe drought: class D2 or worse on the U.S. Drought Monitor, worst class anywhere in the county.

**Cost rule.** Cost = 3 x missed + false alarms. The 3 is our assumption.

| Product | Model and settings | Inputs | Trained on |
|---|---|---|---|
| 4-week alert | Random forest classifier: 100 trees, depth 12, leaf 100, `sqrt` features, balanced class weights, seed 0 | Set H (24 history inputs) | Rio Grande rows, 2000 to 2014 |
| 6-month outlook | Random forest classifier: 80 trees, depth 10, leaf 20, `sqrt` features, seed 0 | Sets H + L + E | Rio Grande rows, forward chaining |
| 12-month outlook | Random forest regressor: 80 trees, depth 10, leaf 20, `sqrt` features, seed 0 | Sets H + L | Rio Grande rows, forward chaining |

**Splits.**

- 4-week alert: train on 2000 to 2014, pick the threshold on 2015 to 2018, test on 2019 to the last labeled week of 2026. A row belongs to a block only if its whole 4-week answer window ends inside it.
- Outlooks: for each test year from 2008 to 2025, train only on rows whose answer window ended before January 1 of that year.

**Thresholds.**

- 4-week alert: **0.36**, the cheapest of the values 0.01, 0.02, ... 1.01 on the Rio Grande validation rows.
- 6-month outlook: 0.25, the break-even point when a miss costs 3 false alarms.

**Baselines the system must beat.**

- 4-week alert: Persistence, D1 now, Worsening, Calendar. The honesty check compares the system with the cheapest of them, not only with persistence.
- 6-month outlook: Persistence, D1 now, Usual for the county, Always warn, Never warn.
- 12-month outlook: Same as now, Same as the last 52 weeks, Usual for the county.

**Extra inputs are ablations only.** River flow and snowpack are tested as extra inputs, with and without, on the same rows. They do not become part of the system whichever way the test falls, because the inputs above were fixed first.

## Validation numbers behind the 4-week threshold

Rio Grande rows, validation years 2015 to 2018 (6,324 county-weeks). Lower cost is better.

| Policy | Cost |
|---|---|
| Our system at threshold 0.36 | 636 |
| Worsening | 655 |
| Persistence | 715 |
| D1 now | 933 |
| Calendar (it chose "never warn") | 3,651 |

These numbers come from `reports/alert_run.txt`.

## Choices made while building, each before seeing its own test result

- The threshold search uses a plain grid from 0.01 to 1.01.
- The Calendar baseline picks its threshold per river, on that river's validation rows.
- One outlook file holds both outlooks, so only issue dates whose full 52-week future is known are scored.
- Flow and snowpack percentiles compare each date with all earlier years back to 1990.
- Snow stations are chosen by rule: SNOTEL stations in hydrologic units 1301 and 1302 with records starting before 1990.

## What will be reported, whichever way it falls

- `honesty_check_pass` for the 4-week alert.
- `beats_every_baseline` for both outlooks.
- The onset result, the transfer result on each river, and the flow and snowpack ablations.

## Addendum, written after the final run (Nov 14, 2026)

This section was added after the final run. Nothing above was edited.

**What "fixed before the final run" does and does not mean.** This record was committed about two minutes before the final run, but after a provisional run of the same code had already shown test-year results. The model settings, inputs and targets came from exploratory scripts in `notebooks/`, which tried several horizons, targets and input sets on the same 2008 to 2025 test years. So this is a record of what was frozen for the final run. It is not a blind pre-registration.

**What an outside review and our own checks found afterwards** (all numbers are in `reports/robustness.json`):

- **No leakage was found.** Features, labels, splits and thresholds were checked and are clean.
- **6-month outlook:** its win over the "D1 or worse now" rule depends on the random seed. Across 10 seeds it beat that rule 3 times. Treat it as a tie.
- **4-week alert:** it beat the Worsening rule with 8 of 10 seeds. A rule that was not in our list, "D2 now, or D1 and worse than 4 or 8 weeks ago", costs 1,840 on the test years against 1,912 for the system, and it was also cheaper on the validation years (622 against 636).
- **12-month outlook:** it beat our three listed baselines with all 10 seeds. But the plain average of two of them ("same as now" and "same as the last 52 weeks") is off by 13.21 weeks, against 14.00 for the system.
- **100 km county rule (53 counties):** the 4-week alert narrowly loses to the Worsening rule (3,269 against 3,243). Both outlooks still beat their listed baselines.
- **El Nino timing:** the 6-month outlook uses a value NOAA publishes a few days into the month, around the days the outlook is issued.

The system was not changed in response to any of this. Changing it now would be tuning on the test years.

## Pivot: canal action (written Nov 14, 2026, before the first run of the reservoir forecast or the trigger test in this code)

The project now asks a decision question: before the irrigation season, should a district seal its leakiest canals this year? Nothing above changes. The settings below were fixed before this code produced any result.

**What we had already seen.** A sandbox run of the trigger test on the existing forecast, before this section was written: issued January to March, the forecast caught 93% of drought seasons and the "D1 or worse now" rule caught 92%. So we expected a tie for the existing forecast. The reservoir forecast had never been run.

**Reservoir forecast (`p_season_res`).** The same 6-month forest with the same settings, trained on Rio Grande rows with the same forward chaining. Inputs are H + L + E plus five reservoir inputs (set R): percent full, its change over 12 and 52 weeks, its rank against the same calendar month in earlier years (back to 1990), and a flag for whether the county has a reservoir. The existing forecast `p_season` is not changed, and the reservoir forecast does not replace it whichever way the test falls.

**County-to-reservoir table.** Ten Texas counties from Val Verde to Cameron use Amistad-Falcon (the two lakes summed). Sierra, Dona Ana, El Paso and Hudspeth use Elephant Butte. The other 17 counties have none. This table is our assumption.

**Trigger test.** Rio Grande rows of the outlook test years, issued in January, February or March. Five rules: our forecast at 0.25, our forecast with reservoirs at 0.25, D1 or worse now, D2 or worse now, seal every year. Value = (drought seasons caught - cost ratio x times fired) / rows, for cost ratios 0.02, 0.05, 0.10, 0.18, 0.25 and 0.50. A forecast "beats the D1 rule" only if its value is higher at cost ratio 0.25.

**Losses.** USDA crop insurance payouts for the cause "Drought", the 31 counties, 2000 to 2025, not adjusted for inflation. "Failure of Irrigation Supply" is reported on its own line and is not in the total.

**What will be reported, whichever way it falls:** both `beats_d1_rule` flags, the 6-month cost with and without reservoir inputs, and the trigger table for the 14 reservoir counties alone.

**Canal map (added later on Nov 14).** Canal and ditch lines for the 31 counties from the U.S. Geological Survey's National Hydrography Dataset (feature type 336). It is a map and a count of km per county. It is not a model input and no result depends on it.

**Canal priority (added later on Nov 14).** A rule, not a trained model: a canal segment is "Inspect first" when the 6-month forecast warns for its county (0.25 or more) and the soil under it is loam or sandier (a published seepage rate of 7.48 gallons per square foot per day or more). Soil comes from the USDA soil survey at the segment's middle point, about 1 meter down. Seepage rates come from Fipps (Texas A&M, 1998). The two cut-offs (0.25 and 7.48) were fixed before the first run. After the first run showed that 6,400 km of canal sat on sandy soils missing from the main table, we added the report's own figures for sand (the low end of its range, 9.34) and for sandy clay loam (one measured canal, 1.69). That raised "Inspect first" from 551 km to 1,421 km. The rule was not tested against measured leaks, because we have none.

## Version 2 (written Nov 14, 2026, before the first run of `v2.py`)

Version 1 above stays as it is and stays the reported system. Version 2 is a second forecast for the Rio Grande that tries to improve on it. It is reported whichever way it falls.

**Why this is not blind.** We have already seen version 1's test-year results. The ideas below came from them: the outside review showed that a simple rule matched the 4-week alert and that an average of two baselines beat the 12-month outlook. So the list of candidates is informed by the test years. What is protected is the choice among them: no candidate is ever chosen using a year it is then scored on.

**Candidates** (the same list for all three products):

- Forest settings: version 1's own, the same with 300 trees, a shallower forest, and a deeper forest.
- Inputs: version 1's own, or the same plus five weather inputs (rain over the last 3, 6 and 12 months against normal, and temperature over the last 3 and 12 months against normal, from NOAA's county record, lagged two months for publication).
- Blend: the forest alone, or 75% or 50% forest with the rest given to a simple rule, or the simple rule alone. The simple rules are "D1 or worse now" (6-month), the average of "same as now" and "same as the last 52 weeks" (12-month), and "Worsening" over 4 weeks or over 4 or 8 weeks (4-week).

**How one is chosen.**

- Outlooks: for each test year from 2008 to 2025, every candidate is scored on the earlier years whose answers were fully known before January 1, and the cheapest is used for that year. Candidates are forecast from 2005 (the first year the 12-month forest has any training rows), only to give the early years some past to judge on. Ties go to version 1.
- 4-week alert: each candidate's threshold is picked on the validation years 2015 to 2018, and the candidate with the lowest validation cost is used. The test years are scored once.
- The 6-month threshold stays 0.25. Cost stays 3 x missed + false alarms.

**What will be reported:** version 2 against version 1 and against the best simple rule for each product, which candidate was chosen each year, the weather inputs on their own, and the result across 5 random seeds. If version 2 is worse, that is what we report.

**Version 2 results (added after the run; nothing above was edited except the start year, 2004 to 2005, fixed before any result existed because the 12-month forest has no training rows for 2004).** All numbers are in `reports/v2.json`.

| Product | Version 1 | Version 2 | Best simple rule | Seeds where v2 beat v1 |
|---|---|---|---|---|
| 4-week alert (cost) | 1,912 | 1,742 | 1,840 | 5 of 5 |
| 6-month outlook (cost) | 2,324 | 2,433 | 2,382 | 3 of 5 |
| 12-month outlook (weeks off) | 14.00 | 13.46 | 13.21 | 5 of 5 |

- **4-week alert: improved.** The validation years chose a deeper forest with weather inputs, blended 75% forest and 25% the "worsening over 4 or 8 weeks" rule. It beats version 1 and the best simple rule. Two cautions: the choice rests on 4 validation years, and that simple rule came from a review made after the test results were known.
- **6-month outlook: not improved.** Choosing by past years did worse than version 1. Version 1 stays, and it still only ties the "D1 or worse now" rule.
- **12-month outlook: better than version 1, but not better than the simple rule.** In 14 of 18 years the past chose the simple rule alone over any forest. The honest reading is that the average of two baselines is the better 12-month forecast.
- **Weather inputs alone did not help** any product (4-week 2,050; 6-month 2,559; 12-month 14.12).

Nothing was changed after seeing these results.

## Districts and the sealant plan (added Nov 14, 2026)

A rule, not a trained model. It adds two links to the canal chain: which irrigation district each canal lies inside, and how an example sealant budget is shared out.

- **Boundaries:** active Irrigation, Water Control & Improvement and Water Improvement districts from the Texas Commission on Environmental Quality, for the Texas Rio Grande counties. A district is listed if it holds at least 5 km of mapped canal (30 districts). We found no public boundary file for New Mexico or Colorado districts, so those states are not covered.
- **District risk:** the 6-month forecast of the district's counties, weighted by canal km. Warning at 0.25, Watch at half of that.
- **Sealant rule:** canals inside a district are ranked by seepage rate x chance of a drought season. The budget pays for canals from the top down. Drains and canals on soil with no published rate are left out.
- **Assumptions, none measured:** every canal is bare earth, has 20 feet of wetted width and carries water for 90 days. The budget ($100,000) is an example. The sealant price ($0.004 per square foot, materials only), its effect (28% to 87% less seepage) and its life (about 3 months) are the same published figures the app's calculator uses.
- **Not tested:** there are no measured leaks or lining records to check the plan against. The rule and its figures were fixed before the first run and not changed after it.

## Live refresh (added Nov 14, 2026)

A daily job downloads the newest drought map, El Nino index, reservoir readings and (monthly) weather, then reruns everything with the same code and settings. Two honest notes:

- **Scores can move.** Each new week gives a few more weeks their real answer, so test-year numbers can shift slightly from one refresh to the next. No model, input, threshold or rule is changed by a refresh.
- **Different computers give slightly different forests.** The first run on GitHub's computer gave version 2 of the 4-week alert a cost of 1,739, against 1,742 on the laptop that produced the numbers above. The cause is rounding inside the forest training, not a change in data or code. The job's own check caught the mismatch and saved nothing. Since then a refresh always reruns version 2 and the export on the same computer, so every published number comes from one run.
- **What moved when GitHub's computer took over (Nov 15, 2026).** The same data and code gave: 6-month outlook cost 2,328 (2,324 on the laptop), version 2 of the 4-week alert 1,739 (1,742), and version 2 of the 6-month outlook won with 2 of 5 seeds (3 of 5). The 4-week alert (1,912), the 12-month outlook (14.0 weeks), the canal levels and the sealant plan did not change. No conclusion changed: the 6-month outlook still ties the "D1 or worse now" rule (2,382). The seed checks in `reports/robustness.json` were run on the laptop and were not rerun.

## Evaluation round 3 (written Nov 15, 2026, before any item below was scored)

Version 1 and its baseline list are unchanged and remain the reported system. Scoring is frozen at 2026-11-10. Added, and labelled as added: year-block intervals (10,000 draws, seed 0); a March-only trigger test; in-fold calibration; the rules "D0 now" and "class-conditional frequency"; an allocation backtest (k = 3, 5, 8, 10, 15; rules A and B as defined in ARCHITECTURE.md); daily inputs lagged 7 days; boosting and a GRU chosen on validation years only; a holdout of six named rivers scored once; a weekly prospective log. The test years are not blind: earlier runs used them. A result counts as a win only if its interval excludes zero. Everything is reported whichever way it falls.

**Physical model, declared at the same time.** Seepage is recomputed from soil-survey permeability, with one factor fitted to the 1998 district loss figures. It is tested by leaving each district out in turn, against two rivals (canal length alone, and the old texture table), each with its own fitted factor. It passes only if a bootstrap over districts of (rival error minus model error) excludes zero. The model is not adjusted after that result is seen.

**What was already known when this was written.** On the machine used for this round (macOS, Python 3.13, the pinned library versions) the unchanged version 1 code gives a 4-week cost of 1912, a 6-month cost of 2324 and a 12-month error of 14.0 weeks. The committed `reports/metrics.json`, produced by the GitHub runner, has 2328 for the 6-month cost. Same code and same data, so the 4-point difference comes from the machine. No round-3 item had been run.

## Physical model: choices fixed on Nov 15, 2026 after the soil download and before any calibration or held-out test was run

The soil download showed two things, written here before the model is fitted or tested so that neither can be adjusted afterwards.

**What was seen.** Permeability exists for 11,710 of 12,171 canal segments. Its spread across soil textures is about 1,400 times (clay to sand), against about 7 times in the 1946 texture table, and the two orderings agree with a rank correlation of 0.70 across texture classes. A water-table depth is recorded for 3,924 segments (0 to 168 cm) and is missing for 8,247.

**What is fixed now.**
- Primary model (M1): seepage = permeability x 2.1205 x water-table factor x one fitted factor, as specified in ARCHITECTURE.md sections 4.1 and 4.3. A missing water-table depth is read as "no water table found in the surveyed profile" and gets a factor of 1. That reading is our assumption.
- Sensitivity model (M2): the same without the water-table factor. It is reported beside M1 whichever does better; it does not replace M1.
- Rivals, each with its own single fitted factor inside the same leave-one-district-out loop: canal length alone, and the 1946 texture table.
- Canal width by class and the lined share are assumptions with ranges (section 4.2). They are not fitted.
- The test, its metric (median absolute percent error on the held-out district, and rank correlation) and its pass rule (a bootstrap over districts of rival error minus model error must exclude zero) are those already declared above. With 18 districts the interval will be wide.
- Known weakness, stated before the result: one fitted factor can move the level of modelled seepage but not its spread, so canals on sand will dominate any ranking built on M1 or M2. If the held-out test does not pass, the site keeps the ranking order only as an illustration and says the volumes are not reliable.
- Nothing here is changed after the held-out result is seen.
