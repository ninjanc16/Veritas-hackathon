// Tests for engine.js. Run with:  node --test app/site/sim/engine.test.js
const test = require("node:test");
const assert = require("node:assert");
const E = require("./engine.js");

// A made-up scope: `years` years of weeks. pct = reservoir % full, cls = drought class, forecast = 0..1.
function scope(years, fill) {
  const weeks = [];
  for (let y = 0; y < years; y++) {
    for (let w = 0; w < 52; w++) {
      const month = Math.min(12, Math.floor(w / 4.34) + 1);
      weeks.push(Object.assign({ year: 2000 + y, month, cls: 0, forecast: 0, pct: 80 }, fill(y, w, month)));
    }
  }
  const canals = [{ km: 10, rate: 9 }, { km: 5, rate: 7 }, { km: 20, rate: 2 }];
  return { weeks, canals, canalsUnranked: canals.slice().reverse(), demandAf: 100000, revenueAtStake: 50e6 };
}
const dry = scope(3, () => ({ pct: 30, cls: 3, forecast: 0.6 }));
const close = (a, b) => assert.ok(Math.abs(a - b) < 1e-6 * Math.max(1, Math.abs(b)), `${a} vs ${b}`);

test("same inputs give the identical result", () => {
  const a = E.simulate(dry, { trigger: "forecast" }), b = E.simulate(dry, { trigger: "forecast" });
  assert.deepStrictEqual(a.totals, b.totals);
  const f1 = E.forward(dry, [{ trigger: "forecast" }], {}, { seed: 3, draws: 20 });
  const f2 = E.forward(dry, [{ trigger: "forecast" }], {}, { seed: 3, draws: 20 });
  assert.deepStrictEqual(f1[0].summary, f2[0].summary);
});

test("water balances every year: wanted = delivered + recovered + still missing", () => {
  for (const trigger of ["never", "declared", "d1", "forecast", "always"]) {
    for (const y of E.simulate(dry, { trigger }).years) close(y.demandAf, y.deliveredAf + y.recoveredAf + y.unmetAf);
  }
});

test("with no canal budget, every policy gives the same outcome", () => {
  const base = E.simulate(dry, { trigger: "never" }, { budget: 0 }).totals;
  for (const trigger of ["declared", "d1", "forecast", "always"]) {
    assert.deepStrictEqual(E.simulate(dry, { trigger }, { budget: 0 }).totals, base);
  }
});

test("a year with no irrigation water loses exactly the published worst case", () => {
  const empty = scope(1, () => ({ pct: 5 }));
  close(E.simulate(empty, { trigger: "never" }).totals.loss, empty.revenueAtStake);
});

test("a full reservoir means no loss, and sealing then earns nothing (a false alarm)", () => {
  const wet = scope(1, () => ({ pct: 90, forecast: 0.9 }));
  const run = E.simulate(wet, { trigger: "forecast" });
  assert.strictEqual(run.totals.loss, 0);
  assert.strictEqual(run.totals.falseAlarms, 1);
  assert.ok(run.totals.spend > 0);
});

test("the forecast policy with the forecast swapped for the D1 rule equals the D1 policy", () => {
  const s = scope(4, (y, w) => ({ pct: 30, cls: (y + w) % 4 }));
  s.weeks.forEach((w) => { w.forecast = w.cls >= 2 ? 1 : 0; });
  assert.deepStrictEqual(E.simulate(s, { trigger: "forecast" }).totals, E.simulate(s, { trigger: "d1" }).totals);
});

test("a decision never uses later weeks", () => {
  const a = scope(1, () => ({ pct: 30, forecast: 0.6 }));
  const b = scope(1, (y, w) => ({ pct: 30, forecast: w > 20 ? 0 : 0.6 }));   // only the future differs
  assert.strictEqual(E.simulate(a, { trigger: "forecast" }).years[0].actedWeek,
                     E.simulate(b, { trigger: "forecast" }).years[0].actedWeek);
});

test("acting in a dry year costs less in total than doing nothing", () => {
  assert.ok(E.simulate(dry, { trigger: "forecast" }).totals.cost < E.simulate(dry, { trigger: "never" }).totals.cost);
});

test("the budget stops at the first canal it cannot cover", () => {
  const p = E.makeParams();
  const cost = (km) => km * E.FEET_PER_KM * p.widthFt * p.usdPerSqft;
  const plan = E.fundCanals(dry.canals, cost(10) + cost(5) - 1, p);   // enough for canal 1, not for canal 2
  assert.strictEqual(plan.funded.length, 1);
});

/* ---- From today, forward ---- */
const today = { startDate: "2026-11-14", pctNow: 38.7, pNow: 0.3, draws: 40, seed: 5 };
// A record with wet years (even) and dry years (odd) before 2020, and absurd years after it.
function history() {
  const s = scope(26, (y, w) => (2000 + y >= 2020 ? { pct: 999, cls: 5 } : y % 2 ? { pct: 30 - w * 0.2, cls: 3 } : { pct: 60 + w * 0.1, cls: 0 }));
  return s;
}

test("from today: the same seed gives the same futures", () => {
  const a = E.fromToday(history(), [{ trigger: "never" }, { trigger: "forecast" }], {}, today);
  const b = E.fromToday(history(), [{ trigger: "never" }, { trigger: "forecast" }], {}, today);
  assert.deepStrictEqual(a.policies[1].summary, b.policies[1].summary);
});

test("from today: storage starts at today's reading and the calendar starts today", () => {
  const run = E.fromToday(history(), [{ trigger: "never" }], {}, today);
  assert.strictEqual(run.fan[0].date, "2026-11-14");
  assert.strictEqual(run.fan[0].low, 38.7);
  assert.strictEqual(run.fan[0].high, 38.7);
});

test("from today: nothing from 2020 or later is learned from", () => {
  const run = E.fromToday(history(), [{ trigger: "never" }], {}, today);
  assert.ok(run.libraryYears.every((y) => y < 2020));
  assert.ok(run.fan.every((w) => w.high <= 100));            // the absurd 999% years never appear
});

test("from today: with no canal budget every policy gives the same futures", () => {
  const run = E.fromToday(history(), [{ trigger: "never" }, { trigger: "forecast" }, { trigger: "always" }], { budget: 0 }, today);
  assert.deepStrictEqual(run.policies[1].draws, run.policies[0].draws);
  assert.deepStrictEqual(run.policies[2].draws, run.policies[0].draws);
});

test("from today: a missed delivery (a storage shock) never makes losses smaller", () => {
  const base = E.fromToday(history(), [{ trigger: "never" }], {}, today);
  const hit = E.fromToday(history(), [{ trigger: "never" }], {}, Object.assign({}, today, { shocks: [{ year: 1, month: 2, points: -10 }] }));
  assert.ok(hit.policies[0].summary.loss.mid >= base.policies[0].summary.loss.mid);
});

test("a second application costs a second round and never recovers less water", () => {
  const one = E.simulate(dry, { trigger: "always" }, { applications: 1 }).totals, two = E.simulate(dry, { trigger: "always" }, { applications: 2 }).totals;
  close(two.spend, 2 * one.spend);
  assert.ok(two.recoveredAf > one.recoveredAf);
});

test("from today: the three futures to watch run from mild to harsh and use only library years", () => {
  const run = E.fromToday(history(), [{ trigger: "never" }, { trigger: "forecast" }], {}, today);
  const cost = (k) => run.cases[k].sample[0].totals.cost;
  assert.ok(cost("best") <= cost("likely") && cost("likely") <= cost("worst"));
  assert.strictEqual(run.cases.likely.sample[0].totals.cost, run.sample[0].totals.cost);
  for (const k of ["best", "likely", "worst"]) assert.ok(run.cases[k].sourceYears.every((y) => y < 2020));
});

test("sealing cannot save water that was never released", () => {
  // Reservoirs far below the "farms get none" line all year: nothing flows, so nothing is saved.
  const weeks = [];
  for (let i = 0; i < 52; i++) weeks.push({ date: "2030-01-01", year: 2030, month: 1 + Math.floor(i / 4.34), cls: 4, forecast: 1, pct: 5 });
  const scope = { weeks, canals: [{ km: 10, rate: 2 }], canalsUnranked: [{ km: 10, rate: 2 }], demandAf: 1000, revenueAtStake: 367000 };
  const run = E.simulate(scope, { trigger: "always" }, { budget: 1e6 });
  assert.strictEqual(run.totals.recoveredAf, 0);
  assert.strictEqual(run.totals.savedAf, 0);
});
