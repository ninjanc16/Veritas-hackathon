/*
  logic.js: the site's arithmetic and wording rules, with no page code. It never touches the
  document, so it runs in the browser (as window.HGLogic) and in Node (for logic.test.js).

  TWO KINDS OF FUNCTION
    Plain ones need nothing but their arguments: esc, usd, num, pct, niceDate, workTime, gal,
    money, usesElephantButte.

    Bound ones read the generated data (window.HG and window.HG_SIM in the browser). They come
    from makeLogic(data), so a test can hand in a small made-up data object instead:
      tierFor, actionFor, planFor, canalNumbers, scopeP, simScope, hitRates, USD_PER_AF.

  WHO USES IT
    js/common.js calls makeLogic once with the real data and republishes the functions under
    their old names on window.HGU. js/platform.js reads the rest from window.HGU.logic.
    sim/engine.js must be loaded first (the budget rule and the unit constants live there).
*/
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory(require("../sim/engine.js"));
  else root.HGLogic = factory(root.HGEngine);
})(typeof self !== "undefined" ? self : this, function (ENGINE) {
  "use strict";

  /* ---------- Formatting ---------- */
  const usd = (x) => {
    if (x == null || isNaN(x)) return "n/a";
    const a = Math.abs(x), sign = x < 0 ? "-" : "";
    if (a >= 1e9) return sign + "$" + (a / 1e9).toFixed(2) + " billion";
    if (a >= 1e6) return sign + "$" + (a / 1e6).toFixed(a >= 1e8 ? 0 : 1) + " million";
    return sign + "$" + Math.round(a).toLocaleString("en-US");
  };
  const num = (x, digits) => (x == null || isNaN(x)) ? "n/a"
    : Number(x).toLocaleString("en-US", { maximumFractionDigits: digits || 0, minimumFractionDigits: digits || 0 });
  const pct = (p) => (p == null ? "n/a" : Math.round(p * 100) + "%");
  const niceDate = (iso) => new Date(iso + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  /* Makes text safe to put inside HTML and inside a double-quoted attribute. It does NOT escape
     the single quote, so it is not safe inside a single-quoted attribute. */
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  /* "3 hours", "2 days", "6 weeks": a length of working time (8-hour days, 5-day weeks) in plain words. */
  function workTime(days) {
    if (days < 1) return Math.max(1, Math.round(days * 8)) + (Math.round(days * 8) <= 1 ? " hour" : " hours");
    if (days < 15) return (days < 3 ? days.toFixed(1) : Math.round(days)) + " days";
    return Math.round(days / 5) + " weeks";
  }

  /* Water is shown in gallons, which people can picture. The engine works in acre-feet
     (the unit water agencies use: 1 acre-foot = 325,851 gallons), so it is converted here. */
  function gal(acreFeet, long) {
    const g = acreFeet * ENGINE.GALLONS_PER_ACRE_FOOT, unit = long ? " gallons" : " gal";
    return g >= 1e9 ? (g / 1e9).toFixed(g >= 1e10 ? 0 : 1) + " billion" + unit : g >= 1e6 ? num(g / 1e6, g < 1e7 ? 1 : 0) + " million" + unit : num(g) + unit;
  }
  /* Short money for tables and charts: "$1.26M", "$12k", "$950". */
  const money = (v) => (v < 0 ? "-" + money(-v) : v >= 1e9 ? "$" + (v / 1e9).toFixed(2) + "B" : v >= 1e6 ? "$" + (v / 1e6).toFixed(v >= 1e8 ? 0 : 1) + "M" : v >= 1e4 ? "$" + Math.round(v / 1e3) + "k" : "$" + num(v));

  const ELEPHANT_BUTTE = ["48141", "48229"];           // El Paso and Hudspeth draw on Elephant Butte
  const usesElephantButte = (d) => d.fips.length > 0 && d.fips.every((f) => ELEPHANT_BUTTE.indexOf(f) >= 0);

  /*
    The functions that read the data.
      data.HG         the generated core data (threshold, plan.assumptions, districts, trigger)
      data.SIM        the generated simulation data (weekly record, reservoirs, the frozen model)
      data.canals     the canals as objects (common.js builds them from HG.canals)
      data.published  the published figures (worstCaseRevenue, valleyIrrigationAf)
    engine is sim/engine.js; left out, the copy this file was loaded with is used.
  */
  function makeLogic(data, engine) {
    const HG = data.HG, SIM = data.SIM, canals = data.canals, PUBLISHED = data.published, E = engine || ENGINE;
    const FROZEN = SIM ? SIM.pre2020 : undefined;         // the forecast model trained only on data before 2020

    /* The advice that goes with a chance of a drought season (the same cut-offs as the canal plan). */
    function actionFor(p) {
      if (p >= HG.threshold) return { key: "seal", title: "Seal and repair before the season",
        text: "The chance of a drought season is over the warning line. Walk the top canals, confirm they are unlined, and seal before the first irrigation." };
      if (p >= HG.threshold / 2) return { key: "inspect", title: "Inspect and prepare",
        text: "Not over the warning line yet. Inspect the top canals and line up sealant so you can act quickly if the forecast rises." };
      return { key: "none", title: "No extra action",
        text: "The chance of a drought season is low. In a normal year canal leakage also refills groundwater, so sealing is not needed." };
    }
    const tierFor = (p) => (p >= HG.threshold ? "Warning" : p >= HG.threshold / 2 ? "Watch" : "Low");

    /*
      The budget plan. scopeCanals = the canals to choose from. pOverride = a "what if" chance of a
      drought season (null = use the model's forecast, which gives exactly the pipeline's order).
      Rule: rank by seepage rate x chance of drought, pay from the top down, stop at the first
      canal the money left cannot cover.
    */
    function planFor(scopeCanals, budget, pOverride) {
      const a = HG.plan.assumptions;
      const treatable = scopeCanals.filter((c) => c.rank != null);
      const ordered = treatable.slice().sort(pOverride == null
        ? (x, y) => x.rank - y.rank
        : (x, y) => (y.rate - x.rate) || (x.rank - y.rank));
      const p = { widthFt: a.wetted_width_ft, usdPerSqft: a.sealant_usd_per_sqft };
      const result = E.fundCanals(ordered, budget, p);
      const days = a.days_one_application_lasts;
      return {
        ordered, funded: result.funded, fundedIds: new Set(result.funded.map((c) => c.id)),
        spent: result.spent, km: result.km,
        savedLow: E.savedAcreFeet(result.gallonsPerDay, days, a.sealant_cut_low),
        savedHigh: E.savedAcreFeet(result.gallonsPerDay, days, a.sealant_cut_high),
        costAll: ordered.reduce((s, c) => s + c.usd, 0),
        sqft: result.km * E.FEET_PER_KM * a.wetted_width_ft,
      };
    }

    /*
      The three numbers that matter for one canal segment (or any list of them):
        usd      what the sealant costs (materials only; the pipeline's price per square foot)
        days     how long the job takes: km / (km one crew seals a day x crews). An assumption.
        afLow, afHigh  acre-feet of water kept in one application, across the range sealant tests found
        worthLow, worthHigh  what that water is worth to farms IF there is a shortage to fill
                             (net crop revenue per acre-foot; in a full year saved water earns nothing)
      params: { kmPerCrewDay, crews } from the simulation's assumptions.
    */
    const USD_PER_AF = PUBLISHED.worstCaseRevenue / PUBLISHED.valleyIrrigationAf;   // about $367, our own division
    function canalNumbers(list, params) {
      const a = HG.plan.assumptions;
      let km = 0, usd = 0, gallonsPerDay = 0;
      list.forEach((c) => {
        const sqft = c.km * E.FEET_PER_KM * a.wetted_width_ft;
        km += c.km; usd += sqft * a.sealant_usd_per_sqft; gallonsPerDay += sqft * (c.rate || 0);
      });
      const afLow = E.savedAcreFeet(gallonsPerDay, a.days_one_application_lasts, a.sealant_cut_low);
      const afHigh = E.savedAcreFeet(gallonsPerDay, a.days_one_application_lasts, a.sealant_cut_high);
      return { km, usd, days: km / (params.kmPerCrewDay * params.crews), crewDays: km / params.kmPerCrewDay,
               afLow, afHigh, worthLow: afLow * USD_PER_AF, worthHigh: afHigh * USD_PER_AF };
    }

    /* The chance of a drought season used by the planner: the "what if" value (severity), or the
       forecast. district = the open district, or null for the state view. */
    function scopeP(severity, district) {
      if (severity != null) return severity;
      if (district) return district.pSeason;
      const km = HG.districts.reduce((s, d) => s + d.canalKm, 0);       // state view: weighted by canal km
      return HG.districts.reduce((s, d) => s + d.pSeason * d.canalKm, 0) / km;
    }

    /* What the engine needs for a list of districts (members): its weekly record, its canals and
       the money at stake. */
    function simScope(members) {
      const system = members.length && usesElephantButte(members[0]) ? "Elephant Butte" : "Amistad-Falcon";
      const fips = Array.from(new Set([].concat.apply([], members.map((x) => x.fips))));
      const ids = new Set(members.map((x) => HG.districts.indexOf(x)));
      const list = canals.filter((c) => ids.has(c.district) && c.rank != null);
      const valleyKm = HG.districts.filter((x) => x.fips.some((f) => SIM.valley.indexOf(f) >= 0)).reduce((s, x) => s + x.canalKm, 0);
      const kmHere = members.reduce((s, x) => s + x.canalKm, 0), share = kmHere / valleyKm;
      // The frozen model's monthly forecasts, per county. A week uses the newest one made on or before it.
      const frozen = fips.map((f) => (FROZEN && FROZEN.monthly[f]) || []), cursor = fips.map(() => -1);
      const start = new Date(SIM.week0 + "T12:00:00Z").getTime(), weeks = [];
      for (let i = 0; i < SIM.nWeeks; i++) {
        const date = new Date(start + i * 7 * 864e5), iso = date.toISOString().slice(0, 10);
        const cls = fips.map((f) => SIM.cls[f][i]).filter((ch) => ch !== ".").map(Number);
        const fc = [];
        frozen.forEach((rows, k) => { while (cursor[k] + 1 < rows.length && rows[cursor[k] + 1][0] <= iso) cursor[k]++; if (cursor[k] >= 0) fc.push(rows[cursor[k]][1]); });
        weeks.push({ date: iso, year: date.getUTCFullYear(), month: date.getUTCMonth() + 1,
                     cls: cls.length ? Math.round(cls.reduce((a, b) => a + b, 0) / cls.length) : null,
                     forecast: fc.length ? fc.reduce((a, b) => a + b, 0) / fc.length : null,
                     pct: SIM.reservoirs[system][i] });
      }
      // Today's forecast from the frozen model, weighted by each district's canal km.
      const live = (FROZEN && FROZEN.live) || {};
      const pOf = (x) => { const v = x.fips.map((f) => live[f]).filter((p) => p != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : x.pSeason; };
      const pNow = members.reduce((s, x) => s + pOf(x) * x.canalKm, 0) / (kmHere || 1);
      return { weeks, canals: list.slice().sort((a, b) => a.rank - b.rank), canalsUnranked: list,
               demandAf: PUBLISHED.valleyIrrigationAf * share, revenueAtStake: PUBLISHED.worstCaseRevenue * share,
               share, system, pNow, ids: Array.from(ids), outsideValley: members.some((x) => !x.fips.some((f) => SIM.valley.indexOf(f) >= 0)), members: members.length };
    }

    /* The frozen model's hit rates on 2020 to 2025, used to decide how often a simulated warning is right. */
    function hitRates() {
      const t = FROZEN ? FROZEN.test.preSeason.forecast : { recall: HG.trigger.rules[0].recall, falseAlarms: HG.trigger.rules[0].false_alarms, rows: HG.trigger.rows, droughtSeasons: HG.trigger.drought_seasons };
      return { recall: t.recall, falseAlarm: t.falseAlarms / Math.max(1, t.rows - t.droughtSeasons) };
    }

    return { actionFor, tierFor, planFor, canalNumbers, USD_PER_AF, scopeP, simScope, hitRates };
  }

  return { usd, num, pct, niceDate, esc, workTime, gal, money, usesElephantButte, makeLogic };
});
