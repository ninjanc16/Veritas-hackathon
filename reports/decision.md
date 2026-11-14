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
