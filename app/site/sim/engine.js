/*
  engine.js: the "do nothing vs act" simulation. No drawing code, so it runs in the browser
  and in Node (for the tests in engine.test.js).

  THE IDEA
  The same weeks of weather and reservoir levels are run through several POLICIES. The water,
  the drought and the prices are identical for every policy. Only the decision differs:

    never     do nothing to the canals
    declared  wait until drought is officially severe (8 straight weeks at D2 or worse),
              then wait for the paperwork, then seal
    d1        seal before the season if the county is ALREADY in drought (D1 or worse)
    forecast  seal before the season if our 6-month forecast is at or over the warning line
    always    seal every year, whatever the forecast says

  EACH WEEK OF THE IRRIGATION SEASON
    1. Farms want  (a year's irrigation water) / (weeks in the season).
    2. The reservoirs decide how much of that is delivered (the "shortage curve" below).
    3. If canals were sealed in the last ~90 days, less water seeps away. That saved water
       only counts if there is a shortage to fill. Saved water in a full year earns nothing.
    4. Every acre-foot still missing costs the same crop revenue.

  Every number that is not measured is a parameter in DEFAULTS with a tag:
    "pipeline"   = comes from our own tested outputs
    "published"  = a figure from a named report
    "assumption" = our own choice; the page shows a slider for it
*/
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.HGEngine = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const GALLONS_PER_ACRE_FOOT = 325851;
  const FEET_PER_KM = 3280.84;
  const D1 = 2;   // drought classes are numbered 0 = none, 1 = D0, 2 = D1, 3 = D2, 4 = D3, 5 = D4
  const D2 = 3;

  const DEFAULTS = {
    budget:        { value: 100000, tag: "assumption", label: "Sealing budget per year ($)" },
    threshold:     { value: 0.25,   tag: "pipeline",   label: "Forecast warning line" },
    usdPerSqft:    { value: 0.004,  tag: "published",  label: "Sealant price per square foot ($, materials only)" },
    widthFt:       { value: 20,     tag: "assumption", label: "Wetted canal width (feet)" },
    cut:           { value: 0.575,  tag: "published",  label: "Share of seepage the sealant stops (tests: 28% to 87%)" },
    daysLast:      { value: 90,     tag: "published",  label: "Days one application lasts" },
    seasonStart:   { value: 2,      tag: "assumption", label: "Irrigation season starts (month)" },
    seasonEnd:     { value: 10,     tag: "assumption", label: "Irrigation season ends (month)" },
    decisionMonth: { value: 3,      tag: "pipeline",   label: "Month the pre-season decision is made" },
    fullAt:        { value: 50,     tag: "assumption", label: "Reservoirs at or over this % full: farms get all their water" },
    zeroAt:        { value: 15,     tag: "assumption", label: "Reservoirs at or under this % full: farms get none" },
    paperworkWeeks:{ value: 8,      tag: "assumption", label: "Weeks from a drought declaration to canal work starting" },
    reliefShare:   { value: 0.3,    tag: "assumption", label: "Share of farm losses later repaid as public relief" },
    jobsPerMillion:{ value: 16.95,  tag: "published",  label: "Jobs at risk per $1 million of crop revenue lost" },
    kmPerCrewDay:  { value: 6,      tag: "assumption", label: "Kilometres of canal one crew seals in a working day" },
    crews:         { value: 2,      tag: "assumption", label: "Crews working at the same time" },
    applications:  { value: 1,      tag: "assumption", label: "Sealant applications in a season you act (each lasts about 90 days)" },
  };

  /* Plain values out of DEFAULTS, with any overrides on top. */
  function makeParams(overrides) {
    const p = {};
    for (const key in DEFAULTS) p[key] = DEFAULTS[key].value;
    return Object.assign(p, overrides || {});
  }

  /* Share of irrigation water NOT delivered, from how full the reservoirs are (0 = none missing, 1 = all). */
  function shortage(pctFull, p) {
    if (pctFull == null) return 0;
    if (pctFull >= p.fullAt) return 0;
    if (pctFull <= p.zeroAt) return 1;
    return (p.fullAt - pctFull) / (p.fullAt - p.zeroAt);
  }

  /*
    The budget rule (the same rule the pipeline uses): pay for canals from the top of the list
    down, and STOP at the first canal the money left cannot cover.
    canals: [{ km, rate (gallons lost per square foot per day), ... }], already in priority order.
  */
  function fundCanals(canals, budget, p) {
    const funded = [];
    let spent = 0, km = 0, gallonsPerDay = 0;
    for (const canal of canals) {
      const sqft = canal.km * FEET_PER_KM * p.widthFt;
      const cost = sqft * p.usdPerSqft;
      if (spent + cost > budget) break;
      spent += cost; km += canal.km; gallonsPerDay += sqft * canal.rate;
      funded.push(canal);
    }
    return { funded, spent, km, gallonsPerDay };
  }

  /* Acre-feet a set of sealed canals stops leaking in a given number of days. */
  function savedAcreFeet(gallonsPerDay, days, cut) {
    return gallonsPerDay * days * cut / GALLONS_PER_ACRE_FOOT;
  }

  /*
    Run one policy through a list of weeks.

    scope:  { weeks: [{ year, month, cls, forecast, pct }], one entry per week, oldest first
              canals: priority-ordered list for fundCanals (the policy's own order is chosen below)
              canalsUnranked: the same canals in map order (used when policy.ranked is false)
              demandAf: acre-feet of irrigation water the scope wants in a full year
              revenueAtStake: crop revenue lost in a year with no irrigation water at all ($) }
    policy: { trigger: "never" | "declared" | "d1" | "forecast" | "always", ranked: true/false }
    Returns { years: [one summary per year], totals }.
  */
  function simulate(scope, policy, overrides) {
    const p = makeParams(overrides);
    const valuePerAf = scope.demandAf > 0 ? scope.revenueAtStake / scope.demandAf : 0;
    const plan = fundCanals(policy.ranked === false ? scope.canalsUnranked : scope.canals, p.budget, p);
    const weeksActive = Math.ceil(p.daysLast / 7);

    // Group the weeks by year, keeping their order.
    const byYear = [];
    for (const week of scope.weeks) {
      if (!byYear.length || byYear[byYear.length - 1].year !== week.year) byYear.push({ year: week.year, weeks: [] });
      byYear[byYear.length - 1].weeks.push(week);
    }

    let d2Run = 0;   // straight weeks at D2 or worse so far (carries across years, like the real record)
    const years = byYear.map(({ year, weeks }) => {
      const inSeason = (w) => w.month >= p.seasonStart && w.month <= p.seasonEnd;
      const seasonWeeks = weeks.filter(inSeason).length || 1;
      const demandWeek = scope.demandAf / seasonWeeks;

      const out = { year, demandAf: 0, deliveredAf: 0, recoveredAf: 0, unmetAf: 0, savedAf: 0,
                    spend: 0, loss: 0, acted: false, actedWeek: null, warnedWeek: null,
                    declaredWeek: null, weeksD2: 0, weeksShort: 0, droughtSeason: false, weekly: [] };
      let sealedUntil = -1;       // index of the last week the sealant still works
      let workStartsAt = null;    // for the "declared" policy: the week the paperwork is done
      let decided = false;        // the pre-season decision is made once a year
      let applied = 0;            // sealant applications so far this year

      weeks.forEach((week, i) => {
        d2Run = week.cls != null && week.cls >= D2 ? d2Run + 1 : 0;
        if (week.cls != null && week.cls >= D2) out.weeksD2 += 1;
        if (d2Run >= 8) out.droughtSeason = true;
        if (out.warnedWeek == null && week.forecast != null && week.forecast >= p.threshold) out.warnedWeek = i;
        if (out.declaredWeek == null && d2Run >= 8) out.declaredWeek = i;

        // --- The decision. A policy may only look at this week and earlier weeks. ---
        let act = false, reapplied = false;
        if (!out.acted && plan.spent > 0) {
          const t = policy.trigger;
          if (!decided && week.month >= p.decisionMonth && (t === "forecast" || t === "d1" || t === "always")) {
            decided = true;
            if (t === "always") act = true;
            if (t === "forecast") act = week.forecast != null && week.forecast >= p.threshold;
            if (t === "d1") act = week.cls != null && week.cls >= D1;
          }
          if (t === "declared") {
            if (workStartsAt == null && d2Run >= 8) workStartsAt = i + p.paperworkWeeks;
            if (workStartsAt != null && i >= workStartsAt && week.month <= p.seasonEnd) act = true;
          }
        }
        if (act) {
          out.acted = true; out.actedWeek = i; out.spend += plan.spent; applied = 1;
          sealedUntil = i + weeksActive - 1;
        }
        // A further application once the last one has worn off, if the plan allows it and the
        // season is still running. Each one is paid for in full.
        if (out.acted && !act && i === sealedUntil + 1 && applied < p.applications && inSeason(week)) {
          applied += 1; out.spend += plan.spent; reapplied = true;
          sealedUntil = i + weeksActive - 1;
        }

        // --- The water. Identical for every policy except the "saved" line. ---
        let demand = 0, missing = 0, saved = 0, recovered = 0;
        if (inSeason(week)) {
          demand = demandWeek;
          missing = demand * shortage(week.pct, p);
          if (i <= sealedUntil) saved = savedAcreFeet(plan.gallonsPerDay, 7, p.cut);
          recovered = Math.min(saved, missing);     // saved water is only worth something in a shortage
          if (missing > 0) out.weeksShort += 1;
        }
        out.demandAf += demand;
        out.deliveredAf += demand - missing;
        out.recoveredAf += recovered;
        out.unmetAf += missing - recovered;
        out.savedAf += saved;
        out.loss += (missing - recovered) * valuePerAf;
        out.weekly.push({ date: week.date, month: week.month, pct: week.pct, cls: week.cls, forecast: week.forecast,
                          demand, missing, recovered, saved, sealed: i <= sealedUntil,
                          spend: act || reapplied ? plan.spent : 0, loss: (missing - recovered) * valuePerAf });
      });

      out.relief = out.loss * p.reliefShare;                       // public money paid AFTER the loss
      out.jobs = out.loss / 1e6 * p.jobsPerMillion;
      out.falseAlarm = out.acted && out.recoveredAf === 0;         // paid for sealing, no shortage to fill
      return out;
    });

    const totals = { spend: 0, loss: 0, relief: 0, recoveredAf: 0, savedAf: 0, unmetAf: 0, jobsWorstYear: 0,
                     yearsActed: 0, falseAlarms: 0, weeksD2: 0, weeksShort: 0 };
    for (const y of years) {
      totals.spend += y.spend; totals.loss += y.loss; totals.relief += y.relief;
      totals.recoveredAf += y.recoveredAf; totals.savedAf += y.savedAf; totals.unmetAf += y.unmetAf;
      totals.jobsWorstYear = Math.max(totals.jobsWorstYear, y.jobs);
      totals.yearsActed += y.acted ? 1 : 0; totals.falseAlarms += y.falseAlarm ? 1 : 0;
      totals.weeksD2 += y.weeksD2; totals.weeksShort += y.weeksShort;
    }
    totals.cost = totals.spend + totals.loss;                      // what the region pays in all: sealing + lost crops
    totals.publicMoney = totals.spend + totals.relief;             // what the public purse pays: sealing + relief
    return { policy, plan: { spent: plan.spent, km: plan.km, canals: plan.funded.length }, years, totals };
  }

  /* A small seeded random number generator, so the same seed always gives the same futures. */
  function makeRng(seed) {
    let a = seed >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  /*
    Many possible futures. Each future is built by picking whole years from the real record
    (so droughts keep their real shape, and each year keeps the forecast the model really made).
    The first year leans dry or wet according to today's forecast: with chance pNow it is drawn
    from the years that had a drought season, otherwise from the years that did not.
    Every policy is run through the SAME futures.
    Returns, per policy, the list of totals (one per future), plus low / middle / high summaries.
  */
  function forward(scope, policies, overrides, options) {
    const opt = Object.assign({ years: 5, draws: 200, seed: 7, pNow: null }, options || {});
    const rng = makeRng(opt.seed);
    const record = {};                                  // year -> its weeks
    for (const w of scope.weeks) (record[w.year] = record[w.year] || []).push(w);
    const full = Object.keys(record).filter((y) => record[y].length >= 50).map(Number);
    const dryRun = simulate(scope, { trigger: "never" }, overrides);
    const dry = new Set(dryRun.years.filter((y) => y.droughtSeason).map((y) => y.year));
    const dryYears = full.filter((y) => dry.has(y)), wetYears = full.filter((y) => !dry.has(y));
    const pick = (list) => list[Math.floor(rng() * list.length)];

    const results = policies.map(() => []);
    for (let d = 0; d < opt.draws; d++) {
      const weeks = [];
      for (let n = 1; n <= opt.years; n++) {
        let source = pick(full);
        if (n === 1 && opt.pNow != null && dryYears.length && wetYears.length) {
          source = rng() < opt.pNow ? pick(dryYears) : pick(wetYears);
        }
        for (const w of record[source]) weeks.push(Object.assign({}, w, { year: n }));
      }
      const future = Object.assign({}, scope, { weeks });
      policies.forEach((policy, i) => results[i].push(simulate(future, policy, overrides).totals));
    }

    const quantile = (values, q) => {
      const sorted = values.slice().sort((a, b) => a - b);
      return sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))];
    };
    return policies.map((policy, i) => {
      const summary = {};
      for (const key of ["cost", "loss", "spend", "publicMoney", "recoveredAf"]) {
        const values = results[i].map((t) => t[key]);
        summary[key] = { low: quantile(values, 0.1), mid: quantile(values, 0.5), high: quantile(values, 0.9) };
      }
      return { policy, draws: results[i], summary };
    });
  }

  /*
    FROM TODAY, FORWARD. This is the simulation the platform shows first.

    What it LEARNS FROM: the "library", whole years of the real record that ended before the
    cut-off (2020). Each library year holds two things per week: the drought class, and how
    much the reservoirs rose or fell that week.

    Where it STARTS: today. The reservoirs start at today's live reading, and the first season
    leans dry or wet according to the forecast the frozen model makes from this week's data.

    How one future is built:
      1. For each coming year, pick a library year at random. For the first season, pick from
         the dry library years with chance pNow, otherwise from the wet ones.
      2. Storage starts at today's level and moves by that library year's weekly rises and falls.
      3. The forecast is not perfect. Before a season that turns out dry it warns with chance
         `recall`; before a season that turns out wet it still warns with chance `falseAlarm`.
         Both come from the frozen model's test on 2020 to 2025.
      4. Shocks (optional) push storage down or up at a chosen moment, in every policy alike.
    Every policy is run through the same futures.

    options: { startDate "YYYY-MM-DD", pctNow, pNow, years, draws, seed, cutoffYear,
               recall, falseAlarm, shocks: [{ year: 1.., month, points }], secondDryYear }
    Returns { policies: [{ policy, draws, summary }], sample: [simulate() result per policy for
              the middle future], fan: weekly low / mid / high storage, libraryYears, dryYears }.
  */
  function fromToday(scope, policies, overrides, options) {
    const opt = Object.assign({ years: 5, draws: 300, seed: 11, pNow: 0.3, pctNow: 50, cutoffYear: 2020,
                                recall: 0.9, falseAlarm: 0.3, shocks: [], secondDryYear: false }, options || {});
    const rng = makeRng(opt.seed);
    const WEEK = 7 * 864e5;

    // The library: full years before the cut-off.
    const record = {};
    for (const w of scope.weeks) if (w.year < opt.cutoffYear) (record[w.year] = record[w.year] || []).push(w);
    const libraryYears = Object.keys(record).map(Number).filter((y) => record[y].length >= 50);
    const library = {};
    for (const y of libraryYears) {
      const weeks = record[y];
      let run = 0, dry = false;
      const rows = weeks.map((w, i) => {
        run = w.cls != null && w.cls >= D2 ? run + 1 : 0;
        if (run >= 8) dry = true;
        const before = i > 0 ? weeks[i - 1].pct : null;
        return { cls: w.cls, change: w.pct != null && before != null ? w.pct - before : 0 };
      });
      library[y] = { rows, dry };
    }
    const dryYears = libraryYears.filter((y) => library[y].dry), wetYears = libraryYears.filter((y) => !library[y].dry);
    const pick = (list) => list[Math.floor(rng() * list.length)];

    // The calendar: one entry a week from the start date to the end of the last simulated year.
    const start = new Date(opt.startDate + "T12:00:00Z").getTime(), startYear = new Date(start).getUTCFullYear();
    const calendar = [];
    for (let t = start; new Date(t).getUTCFullYear() <= startYear + opt.years; t += WEEK) {
      const d = new Date(t), jan1 = Date.UTC(d.getUTCFullYear(), 0, 1);
      calendar.push({ date: d.toISOString().slice(0, 10), year: d.getUTCFullYear(), month: d.getUTCMonth() + 1,
                      weekOfYear: Math.min(51, Math.floor((t - jan1) / WEEK)) });
    }

    const results = policies.map(() => []), futures = [];
    for (let n = 0; n < opt.draws; n++) {
      const source = {}, warned = {};
      for (let y = startYear; y <= startYear + opt.years; y++) {
        const season = y - startYear;                       // 0 = the rest of this year, 1 = the first full season
        let from = pick(libraryYears);
        if (dryYears.length && wetYears.length) {
          if (season === 1) from = rng() < opt.pNow ? pick(dryYears) : pick(wetYears);
          if (season === 2 && opt.secondDryYear) from = pick(dryYears);
        }
        source[y] = from;
        warned[y] = library[from].dry ? rng() < opt.recall : rng() < opt.falseAlarm;
      }
      let pct = opt.pctNow;
      const hit = new Set();
      const weeks = calendar.map((c, i) => {
        const row = library[source[c.year]].rows[Math.min(c.weekOfYear, library[source[c.year]].rows.length - 1)];
        if (i > 0) pct += row.change;
        for (const shock of opt.shocks) {                    // each shock hits once, in its month
          if (!hit.has(shock) && c.year === startYear + shock.year && c.month === shock.month) { hit.add(shock); pct += shock.points; }
        }
        pct = Math.max(0, Math.min(100, pct));
        return { date: c.date, year: c.year, month: c.month, cls: row.cls, forecast: warned[c.year] ? 1 : 0, pct };
      });
      const future = Object.assign({}, scope, { weeks });
      futures.push(future);
      policies.forEach((policy, i) => results[i].push(simulate(future, policy, overrides).totals));
    }

    const quantile = (values, q) => {
      const sorted = values.slice().sort((a, b) => a - b);
      return sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))];
    };
    // The middle future: the one whose do-nothing cost is the median. It is the one the page animates.
    const order = results[0].map((t, i) => [t.cost, i]).sort((a, b) => a[0] - b[0]);
    const middle = order[Math.floor(order.length / 2)][1];
    return {
      policies: policies.map((policy, i) => {
        const summary = {};
        for (const key of ["cost", "loss", "spend", "publicMoney", "recoveredAf"]) {
          const values = results[i].map((t) => t[key]);
          summary[key] = { low: quantile(values, 0.1), mid: quantile(values, 0.5), high: quantile(values, 0.9) };
        }
        return { policy, draws: results[i], summary };
      }),
      sample: policies.map((policy) => simulate(futures[middle], policy, overrides)),
      fan: calendar.map((c, i) => {
        const values = futures.map((f) => f.weeks[i].pct);
        return { date: c.date, low: quantile(values, 0.1), mid: quantile(values, 0.5), high: quantile(values, 0.9) };
      }),
      libraryYears, dryYears,
    };
  }

  return { DEFAULTS, makeParams, shortage, fundCanals, savedAcreFeet, simulate, forward, fromToday, makeRng,
           GALLONS_PER_ACRE_FOOT, FEET_PER_KM };
});
