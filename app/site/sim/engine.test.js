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

/* ---- Physical uncertainty (off unless a run asks for it) ---- */
const band = (b) => b.high - b.low;
const fixedDraw = (over) => Object.assign({ s: 1, seepMult: 1, cut: 0.575, widthMult: 1, linedShare: 0, calibrated: false }, over);
const withPhysics = (s, over) => Object.assign({}, s, { physics: fixedDraw(over) });

test("without a physics draw, simulate gives the totals it gave before physics was added", () => {
  // These numbers were printed by the engine before the physics code was written.
  const a = E.simulate(dry, { trigger: "forecast" }).totals;
  assert.strictEqual(a.spend, 82677.16799999999);
  assert.strictEqual(a.loss, 78693186.32146509);
  assert.strictEqual(a.recoveredAf, 14042.198785641282);
  assert.strictEqual(a.cost, 78775863.48946509);
  const b = E.simulate(dry, { trigger: "declared" }, { budget: 5000 }).totals;
  assert.strictEqual(b.spend, 35433.072);
  assert.strictEqual(b.loss, 80597900.1538608);
  assert.strictEqual(b.savedAf, 10232.771120849713);
  assert.strictEqual(E.simulate(dry, { trigger: "forecast" }).physics, undefined);
});

test("without the physics option, the futures give the bands they gave before physics was added", () => {
  const run = E.fromToday(history(), [{ trigger: "never" }, { trigger: "forecast" }], {}, today);
  assert.deepStrictEqual(run.policies[0].summary.cost, { low: 40000000.00000054, mid: 118000000.00000083, high: 184000000.0000006 });
  assert.deepStrictEqual(run.policies[1].summary.cost, { low: 37687192.59172699, mid: 112517242.32631084, high: 177061577.77517995 });
  assert.deepStrictEqual(run.policies[1].summary.spend, { low: 55118.111999999994, mid: 82677.16799999999, high: 110236.22399999999 });
  assert.deepStrictEqual(run.policies[1].summary.recoveredAf, { low: 7815.10882602216, mid: 12428.04059397327, high: 18722.931714188377 });
  assert.deepStrictEqual(run.cases.likely.sourceYears, [2003, 2002, 2009, 2002, 2019, 2003]);
  assert.deepStrictEqual(run.fan[30], { date: "2027-06-12", low: 32.899999999999935, mid: 39.8, high: 41.599999999999994 });
  assert.strictEqual(run.physics, undefined);
  assert.strictEqual(run.fixedPhysics, undefined);
  const older = E.forward(dry, [{ trigger: "forecast" }], {}, { seed: 3, draws: 20 });
  assert.strictEqual(older[0].summary.cost.mid, 131293105.81577514);
});

test("switching physics on does not change the weather of any future", () => {
  const policies = [{ trigger: "never" }, { trigger: "forecast" }];
  const off = E.fromToday(history(), policies, {}, today), on = E.fromToday(history(), policies, {}, Object.assign({}, today, { physics: true }));
  assert.deepStrictEqual(on.fan, off.fan);
  assert.deepStrictEqual(on.policies[0].draws, off.policies[0].draws);       // doing nothing has no canals in it
  assert.deepStrictEqual(on.cases.likely.sourceYears, off.cases.likely.sourceYears);
});

test("every policy in one future faces the same physics draw, and different futures face different draws", () => {
  const policies = [{ trigger: "never" }, { trigger: "forecast" }, { trigger: "always" }];
  const run = E.fromToday(history(), policies, {}, Object.assign({}, today, { physics: true }));
  for (const key of ["best", "likely", "worst"]) {
    const [nothing, forecast, always] = run.cases[key].sample.map((r) => r.physics);
    for (const part of ["seepMult", "cut", "widthMult", "linedShare"]) {
      assert.strictEqual(typeof nothing[part], "number");
      assert.strictEqual(forecast[part], nothing[part]);
      assert.strictEqual(always[part], nothing[part]);
    }
  }
  assert.strictEqual(run.physics.draws.length, today.draws);
  for (const part of ["seepMult", "cut", "widthMult", "linedShare"]) {
    assert.strictEqual(new Set(run.physics.draws.map((d) => d[part])).size, today.draws, part + " differs in every future");
  }
});

test("a seepage multiplier of zero keeps no water and leaves the sealing bill as it was", () => {
  const base = E.simulate(withPhysics(dry), { trigger: "always" }).totals;
  const none = E.simulate(withPhysics(dry, { seepMult: 0 }), { trigger: "always" }).totals;
  assert.ok(base.savedAf > 0 && base.spend > 0);
  assert.strictEqual(none.savedAf, 0);
  assert.strictEqual(none.recoveredAf, 0);
  assert.strictEqual(none.spend, base.spend);
  assert.strictEqual(none.loss, E.simulate(dry, { trigger: "never" }).totals.loss);   // as if nothing had been done
});

test("canals that are all lined keep no water when sealed and cost the same; with none lined the full saving is kept", () => {
  const plain = E.simulate(dry, { trigger: "always" }).totals;
  const unlined = E.simulate(withPhysics(dry, { linedShare: 0 }), { trigger: "always" }).totals;
  const lined = E.simulate(withPhysics(dry, { linedShare: 1 }), { trigger: "always" }).totals;
  const half = E.simulate(withPhysics(dry, { linedShare: 0.5 }), { trigger: "always" }).totals;
  assert.strictEqual(lined.savedAf, 0);
  assert.strictEqual(lined.spend, plain.spend);
  close(unlined.savedAf, plain.savedAf);
  assert.strictEqual(unlined.spend, plain.spend);
  close(half.savedAf, plain.savedAf / 2);
  assert.strictEqual(half.spend, plain.spend);
});

test("canals twice as wide cost twice as much to seal and keep twice the water", () => {
  const one = E.simulate(withPhysics(dry), { trigger: "always" }), two = E.simulate(withPhysics(dry, { widthMult: 2 }), { trigger: "always" });
  close(two.totals.spend, 2 * one.totals.spend);
  close(two.totals.savedAf, 2 * one.totals.savedAf);
  close(two.plan.spent, 2 * one.plan.spent);
  assert.strictEqual(two.plan.canals, one.plan.canals);                      // the same canals: the plan is made at the assumed width
});

test("the drawn sealant effect is used in place of the fixed one", () => {
  const low = E.simulate(withPhysics(dry, { cut: 0.28 }), { trigger: "always" }).totals, high = E.simulate(withPhysics(dry, { cut: 0.87 }), { trigger: "always" }).totals;
  close(high.savedAf / low.savedAf, 0.87 / 0.28);
  assert.strictEqual(high.spend, low.spend);
  // A slider value for the sealant effect is ignored once a draw is supplied.
  assert.strictEqual(E.simulate(withPhysics(dry, { cut: 0.28 }), { trigger: "always" }, { cut: 0.8 }).totals.savedAf, low.savedAf);
});

test("with physics sampled the bands are at least as wide as with physics held fixed, and the fixed run is returned beside it", () => {
  const policies = [{ trigger: "never" }, { trigger: "always" }];
  const run = E.fromToday(history(), policies, {}, Object.assign({}, today, { physics: true, draws: 200 }));
  const sampled = run.policies[1].summary, fixed = run.fixedPhysics.policies[1].summary;
  assert.ok(fixed.recoveredAf.mid > 0, "sealing keeps water in this fixture");
  assert.ok(band(sampled.recoveredAf) > band(fixed.recoveredAf), `${band(sampled.recoveredAf)} vs ${band(fixed.recoveredAf)}`);
  assert.ok(band(sampled.spend) > band(fixed.spend));
  assert.ok(sampled.recoveredAf.low < fixed.recoveredAf.low && sampled.recoveredAf.high > fixed.recoveredAf.high);
  // Doing nothing involves no canal, so physics cannot move it.
  assert.deepStrictEqual(run.fixedPhysics.policies[0].draws, run.policies[0].draws);
  assert.strictEqual(run.fixedPhysics.policies[1].draws.length, 200);
});

test("physics held fixed sits at the centre of every range", () => {
  const run = E.fromToday(history(), [{ trigger: "never" }], {}, Object.assign({}, today, { physics: true }));
  close(run.physics.central.s, 0.7);
  close(run.physics.central.seepMult, 0.7);
  close(run.physics.central.cut, 0.575);
  assert.strictEqual(run.physics.central.widthMult, 1);
  assert.strictEqual(run.physics.central.linedShare, 0.3);
  assert.strictEqual(run.physics.calibrated, false);
  const calibrated = E.fromToday(history(), [{ trigger: "never" }], {}, Object.assign({}, today, { physics: true, physicsOptions: { seepSd: 0.5 } }));
  assert.strictEqual(calibrated.physics.calibrated, true);
});

test("the count of futures where a policy loses to doing nothing matches the futures themselves", () => {
  // Reservoirs always full: sealing is paid for and never fills a shortage, so it loses every time.
  const wet = scope(26, () => ({ pct: 90, cls: 0 }));
  const policies = [{ trigger: "never" }, { trigger: "always" }];
  for (const physics of [false, true]) {
    const run = E.fromToday(wet, policies, {}, Object.assign({}, today, { physics, pctNow: 90 }));
    assert.strictEqual(run.policies[0].losesToNothing, 0);
    assert.strictEqual(run.policies[1].losesToNothing, today.draws);
    if (physics) assert.strictEqual(run.fixedPhysics.policies[1].losesToNothing, today.draws);
  }
  // Starting right at the full-supply line, some futures turn dry (sealing pays) and some stay full (it does not).
  const mixed = E.fromToday(history(), policies, {}, Object.assign({}, today, { physics: true, pctNow: 50, draws: 200 }));
  for (const set of [mixed.policies, mixed.fixedPhysics.policies]) {
    const lost = set[1].losesToNothing;
    assert.ok(lost > 0 && lost < 200, `${lost} of 200`);
    assert.strictEqual(lost, set[1].draws.filter((t, k) => t.cost > set[0].draws[k].cost).length);
  }
  // With no "do nothing" policy in the list there is nothing to compare with.
  assert.strictEqual(E.fromToday(wet, [{ trigger: "always" }], {}, Object.assign({}, today, { pctNow: 90 })).policies[0].losesToNothing, null);
});

test("samplePhysics stays inside its ranges over many draws and covers most of each", () => {
  const rng = E.makeRng(42), draws = [];
  for (let i = 0; i < 5000; i++) draws.push(E.samplePhysics(rng, { seepSd: 0.4 }));
  const range = (key) => [Math.min(...draws.map((d) => d[key])), Math.max(...draws.map((d) => d[key]))];
  const inside = (key, low, high) => { const [a, b] = range(key); assert.ok(a >= low && b <= high, `${key}: ${a} to ${b}`); assert.ok(a < low + 0.05 * (high - low) && b > high - 0.05 * (high - low), `${key} covers its range`); };
  inside("s", 0.5, 0.9);
  inside("cut", 0.28, 0.87);
  inside("widthMult", 0.4, 2.0);
  inside("linedShare", 0, 0.7);
  assert.ok(draws.every((d) => d.seepMult > 0));
  // The lined share leans towards 0.3: its average is (0 + 0.3 + 0.7) / 3, and more draws fall near 0.3 than near either end.
  const lined = draws.map((d) => d.linedShare), mean = lined.reduce((a, b) => a + b, 0) / lined.length;
  assert.ok(Math.abs(mean - 1 / 3) < 0.01, `mean lined share ${mean}`);
  const near = (x) => lined.filter((v) => Math.abs(v - x) < 0.05).length;
  assert.ok(near(0.3) > 2 * near(0.05) && near(0.3) > 2 * near(0.65));
});

test("samplePhysics gives the same draws for the same seed and different draws for another seed", () => {
  const take = (seed) => { const rng = E.makeRng(seed); return [E.samplePhysics(rng), E.samplePhysics(rng), E.samplePhysics(rng)]; };
  assert.deepStrictEqual(take(9), take(9));
  assert.notDeepStrictEqual(take(9), take(10));
  assert.notDeepStrictEqual(take(9)[0], take(9)[1]);
});

test("samplePhysics without a calibration spread says so, and the seepage multiplier is then just the seepage share", () => {
  const rng = E.makeRng(1);
  for (let i = 0; i < 50; i++) {
    const d = E.samplePhysics(rng, i % 2 ? {} : undefined);
    assert.strictEqual(d.calibrated, false);
    assert.strictEqual(d.seepMult, d.s);
  }
  const d = E.samplePhysics(E.makeRng(1), { seepSd: 0.5 });
  assert.strictEqual(d.calibrated, true);
  assert.notStrictEqual(d.seepMult, d.s);
  assert.strictEqual(E.samplePhysics(E.makeRng(1), { seepSd: 0 }).calibrated, true);   // a spread of zero is still a calibration
});

test("samplePhysics: a calibration spread widens the seepage multiplier around the seepage share", () => {
  const ratios = [], rng = E.makeRng(7);
  for (let i = 0; i < 4000; i++) { const d = E.samplePhysics(rng, { seepSd: 0.5 }); ratios.push(Math.log(d.seepMult / d.s)); }
  const mean = ratios.reduce((a, b) => a + b, 0) / ratios.length;
  const sd = Math.sqrt(ratios.reduce((a, b) => a + (b - mean) * (b - mean), 0) / ratios.length);
  assert.ok(Math.abs(mean) < 0.03, `mean ${mean}`);
  assert.ok(Math.abs(sd - 0.5) < 0.03, `sd ${sd}`);
});

test("samplePhysics: the width range can be set, and per-class widths come back only when asked for", () => {
  const narrow = E.samplePhysics(E.makeRng(3), { widthLow: 1, widthHigh: 1 });
  assert.strictEqual(narrow.widthMult, 1);
  assert.strictEqual(narrow.widthMultByClass, undefined);
  const rng = E.makeRng(3);
  for (let i = 0; i < 200; i++) {
    const d = E.samplePhysics(rng, { widthByClass: { main: [20, 40], ditch: [3, 8] } });
    assert.deepStrictEqual(Object.keys(d.widthMultByClass), ["main", "ditch"]);
    assert.ok(d.widthMultByClass.main >= 1 && d.widthMultByClass.main <= 2);          // 20 to 40 ft over the 20 ft base
    assert.ok(d.widthMultByClass.ditch >= 0.15 && d.widthMultByClass.ditch <= 0.4);   // 3 to 8 ft over 20 ft
  }
});

test("the Normal draw has a mean near 0 and a standard deviation near 1, and is about as often above as below", () => {
  const rng = E.makeRng(123), n = 20000, z = [];
  for (let i = 0; i < n; i++) z.push(E.normal(rng));
  const mean = z.reduce((a, b) => a + b, 0) / n, sd = Math.sqrt(z.reduce((a, b) => a + (b - mean) * (b - mean), 0) / n);
  assert.ok(z.every(Number.isFinite));
  assert.ok(Math.abs(mean) < 0.03, `mean ${mean}`);
  assert.ok(Math.abs(sd - 1) < 0.03, `sd ${sd}`);
  const within1 = z.filter((v) => Math.abs(v) < 1).length / n, within2 = z.filter((v) => Math.abs(v) < 2).length / n;
  assert.ok(Math.abs(within1 - 0.683) < 0.02 && Math.abs(within2 - 0.954) < 0.01, `${within1}, ${within2}`);
});

test("every physics range is listed in DEFAULTS with a tag, and only the sealant range is tagged published", () => {
  const keys = ["cutLow", "cutHigh", "seepShareLow", "seepShareHigh", "widthMultLow", "widthMultHigh", "linedShareLow", "linedShareMode", "linedShareHigh"];
  for (const key of keys) {
    assert.ok(E.DEFAULTS[key] && typeof E.DEFAULTS[key].value === "number" && E.DEFAULTS[key].label.length > 0, key);
    assert.strictEqual(E.DEFAULTS[key].tag, key.indexOf("cut") === 0 ? "published" : "assumption", key);
  }
  assert.strictEqual(E.DEFAULTS.cut.value, 0.575);                            // the page's slider still starts here
  assert.strictEqual(E.DEFAULTS.cut.tag, "assumption");                       // only the range is published, not its middle
});
