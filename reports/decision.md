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
