// Tests for logic.js. Run with:  node app/site/js/logic.test.js
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const L = require("./logic.js");
const E = require("../sim/engine.js");

const close = (a, b) => assert.ok(Math.abs(a - b) < 1e-9 * Math.max(1, Math.abs(b)), `${a} vs ${b}`);

/*
  A small made-up data object, shaped like the generated files.
  Sealant here costs 3280.84 ft x 10 ft x $0.01 = $328.084 for each kilometre of canal.
*/
const USD_PER_KM = 328.084;
function fake() {
  const X = { name: "X", fips: ["A", "B"], pSeason: 0.6, canalKm: 30 };          // in the "valley" (county A)
  const Y = { name: "Y", fips: ["C"], pSeason: 0.2, canalKm: 10 };               // outside it
  const Z = { name: "Z", fips: ["48141"], pSeason: 0.1, canalKm: 20 };           // El Paso: the other reservoir
  const HG = {
    threshold: 0.25,
    plan: { assumptions: { wetted_width_ft: 10, sealant_usd_per_sqft: 0.01, sealant_cut_low: 0.28, sealant_cut_high: 0.87, days_one_application_lasts: 90 } },
    districts: [X, Y, Z],
    trigger: { rows: 20, drought_seasons: 20, rules: [{ recall: 0.8, false_alarms: 5 }] },
  };
  // Six weeks from Tuesday 2019-12-31. "." = no drought reading that week.
  const SIM = {
    week0: "2019-12-31", nWeeks: 6, valley: ["A"],
    cls: { A: "012345", B: "1.4.0.", C: "......", "48141": "555555" },
    reservoirs: { "Amistad-Falcon": [50, 49, 48, 47, 46, 45], "Elephant Butte": [10, 11, 12, 13, 14, 15] },
    pre2020: {
      monthly: { A: [["2020-01-07", 0.1, 0], ["2020-01-21", 0.5, 1]], B: [["2020-01-14", 0.3, 0]] },
      live: { A: 0.4 },
      test: { preSeason: { forecast: { recall: 0.9, falseAlarms: 10, rows: 100, droughtSeasons: 60 } } },
    },
  };
  // In map order, not in rank order. usd is the pipeline's own cost figure for the canal.
  const canals = [
    { id: 0, name: "B", km: 2, rate: 2, rank: 2, usd: 656, district: 0 },
    { id: 1, name: "drain", km: 3, rate: null, rank: null, usd: 0, district: 0 },
    { id: 2, name: "D", km: 0.5, rate: 5, rank: 4, usd: 164, district: 1 },
    { id: 3, name: "A", km: 1, rate: 9, rank: 1, usd: 328, district: 0 },
    { id: 4, name: "C", km: 4, rate: 7, rank: 3, usd: 1312, district: 1 },
  ];
  const published = { worstCaseRevenue: 1000, valleyIrrigationAf: 10 };            // $100 for each acre-foot
  return { HG, SIM, canals, published, X, Y, Z };
}
const logic = (data) => L.makeLogic(data || fake());
const names = (list) => list.map((c) => c.name);

/* ---------- esc ---------- */
test("esc escapes all five characters that matter in HTML text and attributes: & < > and both quotes", () => {
  assert.strictEqual(L.esc("&"), "&amp;");
  assert.strictEqual(L.esc("<"), "&lt;");
  assert.strictEqual(L.esc(">"), "&gt;");
  assert.strictEqual(L.esc('"'), "&quot;");
  assert.strictEqual(L.esc("'"), "&#39;");
  assert.strictEqual(L.esc('<a href="x">Tom & Jerry</a>'), "&lt;a href=&quot;x&quot;&gt;Tom &amp; Jerry&lt;/a&gt;");
  assert.strictEqual(L.esc("O'Brien"), "O&#39;Brien");
  assert.strictEqual(L.esc("&amp;"), "&amp;amp;");                        // escaping twice shows the first escape as text
});

test("esc leaves nothing that can open a tag or close an attribute, with either kind of quote", () => {
  const hostile = ['"><script>alert(1)</script>', "' onmouseover='alert(1)", "<img src=x onerror=alert(1)>", '</td><td class="x">', "a\" b' c<d>e&f"];
  for (const text of hostile) assert.ok(!/[<>"']/.test(L.esc(text)), text);
});

test("esc turns null and undefined into an empty string and other values into text", () => {
  assert.strictEqual(L.esc(null), "");
  assert.strictEqual(L.esc(undefined), "");
  assert.strictEqual(L.esc(0), "0");
  assert.strictEqual(L.esc(12.5), "12.5");
  assert.strictEqual(L.esc("plain text"), "plain text");
});

/* ---------- safeUrl, cssClass, finiteOrNull ---------- */
test("safeUrl keeps an address that starts with https:// or http:// exactly as it is", () => {
  assert.strictEqual(L.safeUrl("https://example.org/a?b=1&c=2"), "https://example.org/a?b=1&c=2");
  assert.strictEqual(L.safeUrl("http://example.org"), "http://example.org");
});

test("safeUrl gives null for anything that is not a plain web address", () => {
  const hostile = ["javascript:alert(1)", "JAVASCRIPT:alert(1)", " javascript:alert(1)", "java\tscript:alert(1)", "data:text/html,<script>alert(1)</script>",
    "vbscript:x", "//example.org", "/relative/path", "example.org", "ftp://example.org", " https://example.org", "HTTPS://example.org", "https:/example.org", "https:example.org", "",
    null, undefined, 0, 12, {}, ["https://example.org"], { toString: () => "https://example.org" }];
  for (const url of hostile) assert.strictEqual(L.safeUrl(url), null, String(url));
});

test("safeUrl does not escape: a kept address with a quote or a tag in it still needs esc before it goes in an attribute", () => {
  const url = 'https://example.org/"><script>alert(1)</script>';
  assert.strictEqual(L.safeUrl(url), url);
  assert.ok(!/[<>"']/.test(L.esc(L.safeUrl(url))));
});

test("cssClass keeps a known class name and gives an empty string for anything else", () => {
  for (const tier of ["Low", "Watch", "Warning"]) assert.strictEqual(L.cssClass(tier, L.TIER_CLASSES), tier);
  for (const sev of ["Critical", "Important", "Context"]) assert.strictEqual(L.cssClass(sev, L.SEVERITY_CLASSES), sev);
  const hostile = ['Warning" onmouseover="alert(1)', "Warning x", "warning", " Warning", "Low'><script>", "<b>", "", null, undefined, 0, {}, ["Low"], "constructor", "length", "0"];
  for (const value of hostile) assert.strictEqual(L.cssClass(value, L.TIER_CLASSES), "", String(value));
  assert.strictEqual(L.cssClass("Critical", L.TIER_CLASSES), "");          // a severity is not a tier
});

test("finiteOrNull keeps a real number and gives null for everything else", () => {
  for (const x of [0, -0.5, 41.3, 100, 1e9]) assert.strictEqual(L.finiteOrNull(x), x);
  for (const x of [NaN, Infinity, -Infinity, null, undefined, "", "41.3", "<script>alert(1)</script>", true, {}, [41.3]]) assert.strictEqual(L.finiteOrNull(x), null, String(x));
});

test("percentOrNull keeps a real number from 0 to 100 inclusive and gives null for everything else", () => {
  for (const x of [0, 0.1, 38.7, 99.9, 100]) assert.strictEqual(L.percentOrNull(x), x);
  for (const x of [-0.1, -5, 100.1, 250, NaN, Infinity, -Infinity, null, undefined, "", "38.7", "50%", "<script>alert(1)</script>", true, {}, [50]]) {
    assert.strictEqual(L.percentOrNull(x), null, String(x));
  }
});

test("safeDecode decodes a well-formed link fragment", () => {
  assert.strictEqual(L.safeDecode("state"), "state");
  assert.strictEqual(L.safeDecode("d=Delta%20Lake%20Irrigation%20District"), "d=Delta Lake Irrigation District");
  assert.strictEqual(L.safeDecode("d=Ca%C3%B1on%20%26%20Sons"), "d=Ca\u00f1on & Sons");
  assert.strictEqual(L.safeDecode(""), "");
  assert.strictEqual(L.safeDecode(null), "");
  assert.strictEqual(L.safeDecode(undefined), "");
});

test("safeDecode returns a malformed fragment as it came, where the browser's decoder would throw", () => {
  for (const bad of ["%", "d=Delta%", "d=Delta%2", "%E0%A4%A", "d=%C3", "%zz", "state%"]) {
    assert.throws(() => decodeURIComponent(bad), URIError, bad);            // this is the failure being guarded
    assert.strictEqual(L.safeDecode(bad), bad);
  }
});

/* ---------- csvText, csvNumber ---------- */
test("csvText puts every text field in double quotes and doubles a double quote inside it", () => {
  assert.strictEqual(L.csvText("Main Canal"), '"Main Canal"');
  assert.strictEqual(L.csvText('The "Big" Ditch'), '"The ""Big"" Ditch"');
  assert.strictEqual(L.csvText("a,b"), '"a,b"');
  assert.strictEqual(L.csvText("two\nlines"), '"two\nlines"');
  assert.strictEqual(L.csvText("O'Brien Lateral"), '"O\'Brien Lateral"');
  assert.strictEqual(L.csvText("48061"), '"48061"');
  assert.strictEqual(L.csvText(""), '""');
  assert.strictEqual(L.csvText(null), '""');
  assert.strictEqual(L.csvText(undefined), '""');
  assert.strictEqual(L.csvText('","x'), '""",""x"');                        // cannot break out into a new field
});

test("csvText puts a single quote before a field that a spreadsheet would read as a formula", () => {
  assert.strictEqual(L.csvText("=SUM(A1:A9)"), '"\'=SUM(A1:A9)"');
  assert.strictEqual(L.csvText('=HYPERLINK("http://evil","x")'), '"\'=HYPERLINK(""http://evil"",""x"")"');
  assert.strictEqual(L.csvText("+1+1"), '"\'+1+1"');
  assert.strictEqual(L.csvText("-2+3"), '"\'-2+3"');
  assert.strictEqual(L.csvText("@SUM(1)"), '"\'@SUM(1)"');
  assert.strictEqual(L.csvText("\t=1+1"), '"\'\t=1+1"');
  assert.strictEqual(L.csvText("\r=1+1"), '"\'\r=1+1"');
  assert.strictEqual(L.csvText(-5), '"\'-5"');                              // a number passed as text is treated as text
});

test("csvText leaves a field alone when the risky character is not the first one", () => {
  assert.strictEqual(L.csvText("A=B"), '"A=B"');
  assert.strictEqual(L.csvText("Canal - East"), '"Canal - East"');
  assert.strictEqual(L.csvText("name@example"), '"name@example"');
  assert.strictEqual(L.csvText(" =1+1"), '" =1+1"');
});

test("csvNumber writes a real number bare, with fixed decimals if asked, and leaves anything else empty", () => {
  assert.strictEqual(L.csvNumber(9.35), "9.35");
  assert.strictEqual(L.csvNumber(0), "0");
  assert.strictEqual(L.csvNumber(-1.5), "-1.5");
  assert.strictEqual(L.csvNumber(288.984, 2), "288.98");
  assert.strictEqual(L.csvNumber(1225.2, 2), "1225.20");
  assert.strictEqual(L.csvNumber(0, 2), "0.00");
  for (const x of [NaN, Infinity, -Infinity, null, undefined, "", "12", "=1+1", "<b>", {}, [1]]) {
    assert.strictEqual(L.csvNumber(x), "", String(x));
    assert.strictEqual(L.csvNumber(x, 2), "", String(x));
  }
});

/* ---------- usd, num, pct, niceDate ---------- */
test("usd says n/a for a missing value and writes whole dollars under a million", () => {
  for (const x of [null, undefined, NaN, "abc"]) assert.strictEqual(L.usd(x), "n/a");
  assert.strictEqual(L.usd(0), "$0");
  assert.strictEqual(L.usd(0.4), "$0");
  assert.strictEqual(L.usd(1234.5), "$1,235");
  assert.strictEqual(L.usd(999999), "$999,999");
  assert.strictEqual(L.usd(-5), "-$5");
});

test("usd changes unit exactly at one million, one hundred million and one billion", () => {
  assert.strictEqual(L.usd(1e6), "$1.0 million");
  assert.strictEqual(L.usd(99.9e6), "$99.9 million");
  assert.strictEqual(L.usd(1e8), "$100 million");
  assert.strictEqual(L.usd(999e6), "$999 million");
  assert.strictEqual(L.usd(1e9), "$1.00 billion");
  assert.strictEqual(L.usd(-2.5e9), "-$2.50 billion");
  assert.strictEqual(L.usd(-1.5e6), "-$1.5 million");
});

test("num says n/a for a missing value, groups thousands and keeps the digits asked for", () => {
  for (const x of [null, undefined, NaN]) assert.strictEqual(L.num(x), "n/a");
  assert.strictEqual(L.num(0), "0");
  assert.strictEqual(L.num(1234.567), "1,235");
  assert.strictEqual(L.num(1234.567, 2), "1,234.57");
  assert.strictEqual(L.num(5, 2), "5.00");
  assert.strictEqual(L.num(-1234), "-1,234");
  assert.strictEqual(L.num("12"), "12");
});

test("pct rounds a share to a whole percent and says n/a for null", () => {
  assert.strictEqual(L.pct(null), "n/a");
  assert.strictEqual(L.pct(undefined), "n/a");
  assert.strictEqual(L.pct(0), "0%");
  assert.strictEqual(L.pct(0.25), "25%");
  assert.strictEqual(L.pct(0.254), "25%");
  assert.strictEqual(L.pct(1), "100%");
  assert.strictEqual(L.pct(-0.1), "-10%");
});

test("pct does not guard against NaN (today's behaviour)", () => {
  assert.strictEqual(L.pct(NaN), "NaN%");
});

test("niceDate writes an ISO day as month, day, year and does not slip a day", () => {
  assert.strictEqual(L.niceDate("2026-11-10"), "Nov 10, 2026");
  assert.strictEqual(L.niceDate("2020-01-01"), "Jan 1, 2020");
  assert.strictEqual(L.niceDate("2024-02-29"), "Feb 29, 2024");
});

/* ---------- workTime ---------- */
test("workTime counts hours under one day, never less than one hour", () => {
  assert.strictEqual(L.workTime(0), "1 hour");
  assert.strictEqual(L.workTime(-1), "1 hour");
  assert.strictEqual(L.workTime(0.125), "1 hour");
  assert.strictEqual(L.workTime(0.25), "2 hours");
  assert.strictEqual(L.workTime(0.99), "8 hours");
});

test("workTime changes to days at exactly 1 day, drops the decimal at 3 days, and changes to weeks at 15 days", () => {
  assert.strictEqual(L.workTime(1), "1.0 days");
  assert.strictEqual(L.workTime(2.99), "3.0 days");
  assert.strictEqual(L.workTime(3), "3 days");
  assert.strictEqual(L.workTime(14.9), "15 days");
  assert.strictEqual(L.workTime(15), "3 weeks");
  assert.strictEqual(L.workTime(100), "20 weeks");
});

/* ---------- gal, money ---------- */
test("gal turns acre-feet into gallons and changes unit at a million and a billion", () => {
  assert.strictEqual(L.gal(0), "0 gal");
  assert.strictEqual(L.gal(1), "325,851 gal");
  assert.strictEqual(L.gal(1, true), "325,851 gallons");
  assert.strictEqual(L.gal(10), "3.3 million gal");                       // 3,258,510
  assert.strictEqual(L.gal(100), "33 million gal");                       // no decimal from 10 million up
  assert.strictEqual(L.gal(10000), "3.3 billion gal");
  assert.strictEqual(L.gal(100000, true), "33 billion gallons");          // no decimal from 10 billion up
});

test("money shortens to k, M and B exactly at ten thousand, one million and one billion", () => {
  assert.strictEqual(L.money(0), "$0");
  assert.strictEqual(L.money(950), "$950");
  assert.strictEqual(L.money(9999), "$9,999");
  assert.strictEqual(L.money(1e4), "$10k");
  assert.strictEqual(L.money(999499), "$999k");
  assert.strictEqual(L.money(1e6), "$1.0M");
  assert.strictEqual(L.money(99.9e6), "$99.9M");
  assert.strictEqual(L.money(1e8), "$100M");
  assert.strictEqual(L.money(1e9), "$1.00B");
  assert.strictEqual(L.money(-5e6), "-$5.0M");
  assert.strictEqual(L.money(-12), "-$12");
});

/* ---------- tierFor, actionFor ---------- */
test("tierFor: Warning at the warning line, Watch at half of it, Low under that", () => {
  const { tierFor } = logic();                                            // the line is 0.25
  assert.strictEqual(tierFor(1), "Warning");
  assert.strictEqual(tierFor(0.25), "Warning");
  assert.strictEqual(tierFor(0.2499), "Watch");
  assert.strictEqual(tierFor(0.125), "Watch");
  assert.strictEqual(tierFor(0.1249), "Low");
  assert.strictEqual(tierFor(0), "Low");
  assert.strictEqual(tierFor(-0.3), "Low");
});

test("tierFor gives Low for a missing chance (null or NaN)", () => {
  const { tierFor } = logic();
  assert.strictEqual(tierFor(null), "Low");
  assert.strictEqual(tierFor(NaN), "Low");
});

test("actionFor uses the same two cut-offs as tierFor: seal, inspect, none", () => {
  const { actionFor } = logic();
  assert.strictEqual(actionFor(0.25).key, "seal");
  assert.strictEqual(actionFor(0.9).key, "seal");
  assert.strictEqual(actionFor(0.2499).key, "inspect");
  assert.strictEqual(actionFor(0.125).key, "inspect");
  assert.strictEqual(actionFor(0.1249).key, "none");
  assert.strictEqual(actionFor(0).key, "none");
  assert.strictEqual(actionFor(null).key, "none");
  assert.strictEqual(actionFor(NaN).key, "none");
  for (const p of [0.9, 0.2, 0]) { const a = actionFor(p); assert.ok(a.title.length > 0 && a.text.length > 0); }
});

test("tierFor and actionFor follow the warning line in the data, not a fixed number", () => {
  const data = fake(); data.HG.threshold = 0.6;
  const { tierFor, actionFor } = logic(data);
  assert.strictEqual(tierFor(0.5), "Watch");
  assert.strictEqual(tierFor(0.29), "Low");
  assert.strictEqual(actionFor(0.6).key, "seal");
});

/* ---------- planFor ---------- */
test("planFor pays for canals in rank order and leaves out canals with no rank", () => {
  const data = fake(), plan = logic(data).planFor(data.canals, 1e9, null);
  assert.deepStrictEqual(names(plan.ordered), ["A", "B", "C", "D"]);       // the drain has no rank
  assert.deepStrictEqual(names(plan.funded), ["A", "B", "C", "D"]);
  assert.deepStrictEqual(Array.from(plan.fundedIds).sort(), [0, 2, 3, 4]);
  close(plan.km, 7.5);
  close(plan.spent, 7.5 * USD_PER_KM);                                     // $2,460.63
  assert.strictEqual(plan.costAll, 328 + 656 + 1312 + 164);                // the pipeline's own figures, added up
});

test("planFor: funded set, money spent, kilometres and water kept match a hand calculation", () => {
  // Budget $1,200. A costs $328.084 and B $656.168: $984.252 spent. C would cost $1,312.336.
  const data = fake(), plan = logic(data).planFor(data.canals, 1200, null);
  assert.deepStrictEqual(names(plan.funded), ["A", "B"]);
  close(plan.spent, 984.252);
  close(plan.km, 3);
  close(plan.sqft, 3 * 3280.84 * 10);                                      // 98,425.2 square feet
  // Leak: A 32,808.4 sq ft x 9 + B 65,616.8 sq ft x 2 = 426,509.2 gallons a day.
  // Kept in 90 days: x 90 x 0.28 / 325,851 = 32.9845 acre-feet, and x 0.87 = 102.4875.
  close(plan.savedLow, 426509.2 * 90 * 0.28 / 325851);
  close(plan.savedHigh, 426509.2 * 90 * 0.87 / 325851);
  assert.ok(Math.abs(plan.savedLow - 32.9845) < 1e-4 && Math.abs(plan.savedHigh - 102.4875) < 1e-4);
});

test("planFor stops at the first canal the money left cannot cover, even if a cheaper one comes after it", () => {
  // After A and B, $215.748 is left. C ($1,312.336) does not fit, so the plan stops.
  // D ($164.042) would fit, and is still not funded.
  const data = fake(), plan = logic(data).planFor(data.canals, 1200, null);
  assert.ok(1200 - plan.spent > 0.5 * USD_PER_KM);                         // D alone was affordable
  assert.ok(!plan.fundedIds.has(2));
  assert.deepStrictEqual(names(plan.funded), ["A", "B"]);
});

test("planFor funds a canal whose cost equals the money left, and not one that costs a cent more", () => {
  const data = fake(), { planFor } = logic(data);
  const costA = 1 * E.FEET_PER_KM * 10 * 0.01;
  assert.deepStrictEqual(names(planFor(data.canals, costA, null).funded), ["A"]);
  assert.deepStrictEqual(names(planFor(data.canals, costA - 0.01, null).funded), []);
  assert.strictEqual(planFor(data.canals, 0, null).spent, 0);
});

test("planFor with a what-if chance re-orders by seepage rate, highest first, and applies the same stop rule", () => {
  const data = fake(), { planFor } = logic(data);
  const all = planFor(data.canals, 1e9, 0.5);
  assert.deepStrictEqual(names(all.ordered), ["A", "C", "D", "B"]);        // rates 9, 7, 5, 2
  // Budget $1,200: A is paid ($328.084); C is next and does not fit; D and B are never reached.
  assert.deepStrictEqual(names(planFor(data.canals, 1200, 0.5).funded), ["A"]);
  // The what-if value itself does not change the order: any value that is not null gives the same list.
  assert.deepStrictEqual(names(planFor(data.canals, 1e9, 0).ordered), ["A", "C", "D", "B"]);
  assert.deepStrictEqual(names(planFor(data.canals, 1e9, undefined).ordered), ["A", "B", "C", "D"]);   // undefined counts as "no override"
});

test("planFor with a what-if chance breaks a tie in seepage rate by the pipeline's rank", () => {
  const data = fake();
  data.canals.forEach((c) => { if (c.rate != null) c.rate = 3; });
  assert.deepStrictEqual(names(logic(data).planFor(data.canals, 1e9, 0.8).ordered), ["A", "B", "C", "D"]);
});

test("planFor does not change the list it is given", () => {
  const data = fake(), before = names(data.canals);
  logic(data).planFor(data.canals, 1200, 0.5);
  assert.deepStrictEqual(names(data.canals), before);
});

/* ---------- canalNumbers ---------- */
test("canalNumbers: cost, crew time and acre-feet for one segment match a hand calculation", () => {
  // 2 km x 3,280.84 ft x 10 ft wide = 65,616.8 sq ft. Sealant at $0.01: $656.168.
  // Leak at 5 gallons per sq ft a day: 328,084 gallons a day.
  // Kept in 90 days: x 90 x 0.28 / 325,851 = 25.3727 acre-feet, and x 0.87 = 78.8366.
  const n = logic().canalNumbers([{ km: 2, rate: 5 }], { kmPerCrewDay: 4, crews: 2 });
  close(n.km, 2);
  close(n.usd, 656.168);
  close(n.crewDays, 0.5);                                                  // one crew: 2 km at 4 km a day
  close(n.days, 0.25);                                                     // two crews
  close(n.afLow, 328084 * 90 * 0.28 / 325851);
  close(n.afHigh, 328084 * 90 * 0.87 / 325851);
  assert.ok(Math.abs(n.afLow - 25.3727) < 1e-4 && Math.abs(n.afHigh - 78.8366) < 1e-4);
  close(n.worthLow, n.afLow * 100);                                        // $100 an acre-foot in the made-up data
  close(n.worthHigh, n.afHigh * 100);
});

test("canalNumbers adds segments up, and a segment with no seepage rate costs money but keeps no water", () => {
  const { canalNumbers, USD_PER_AF } = logic(), P = { kmPerCrewDay: 6, crews: 2 };
  assert.strictEqual(USD_PER_AF, 100);
  const one = canalNumbers([{ km: 2, rate: 5 }], P), two = canalNumbers([{ km: 2, rate: 5 }, { km: 3, rate: null }], P);
  close(two.km, 5);
  close(two.usd, 5 * USD_PER_KM);
  close(two.afLow, one.afLow);
  const none = canalNumbers([], P);
  assert.deepStrictEqual([none.km, none.usd, none.days, none.afLow, none.afHigh], [0, 0, 0, 0, 0]);
});

/* ---------- scopeP ---------- */
test("scopeP: a what-if value wins, then the open district's forecast, then the state average weighted by canal km", () => {
  const data = fake(), { scopeP } = logic(data);
  assert.strictEqual(scopeP(0.8, data.X), 0.8);
  assert.strictEqual(scopeP(0, data.X), 0);                                // a what-if of zero is still a what-if
  assert.strictEqual(scopeP(null, data.X), 0.6);
  // (0.6 x 30 + 0.2 x 10 + 0.1 x 20) / 60 km = 22 / 60
  close(scopeP(null, null), 22 / 60);
});

/* ---------- simScope ---------- */
test("simScope: one entry a week, seven days apart from the first week, with the calendar year and month of each", () => {
  const data = fake(), s = logic(data).simScope([data.X]);
  assert.deepStrictEqual(s.weeks.map((w) => w.date), ["2019-12-31", "2020-01-07", "2020-01-14", "2020-01-21", "2020-01-28", "2020-02-04"]);
  assert.deepStrictEqual(s.weeks.map((w) => w.year), [2019, 2020, 2020, 2020, 2020, 2020]);
  assert.deepStrictEqual(s.weeks.map((w) => w.month), [12, 1, 1, 1, 1, 2]);
});

test("simScope: week i reads position i of the drought record and of the reservoir record", () => {
  const data = fake(), s = logic(data).simScope([data.X]);
  // Counties A "012345" and B "1.4.0.": the average of the readings that exist, rounded (0.5 rounds up).
  assert.deepStrictEqual(s.weeks.map((w) => w.cls), [1, 1, 3, 3, 2, 5]);
  assert.deepStrictEqual(s.weeks.map((w) => w.pct), [50, 49, 48, 47, 46, 45]);
  assert.strictEqual(s.system, "Amistad-Falcon");
});

test("simScope: a week uses the newest forecast made on or before it, and never a later one", () => {
  const data = fake(), s = logic(data).simScope([data.X]);
  // A: 0.1 from 7 Jan, 0.5 from 21 Jan. B: 0.3 from 14 Jan. The week's value is the counties' average.
  const fc = s.weeks.map((w) => w.forecast);
  assert.strictEqual(fc[0], null);                                         // 31 Dec: nothing has been made yet
  close(fc[1], 0.1);                                                       // 7 Jan: made that very day counts
  close(fc[2], 0.2);                                                       // 14 Jan: (0.1 + 0.3) / 2
  close(fc[3], 0.4);                                                       // 21 Jan: (0.5 + 0.3) / 2
  close(fc[4], 0.4);
  close(fc[5], 0.4);
});

test("simScope: a week with no drought reading in any county has a null class, and no forecast gives null", () => {
  const data = fake(), s = logic(data).simScope([data.Y]);                 // county C: "......", no forecasts
  assert.ok(s.weeks.every((w) => w.cls === null && w.forecast === null));
});

test("simScope: canals are the members' ranked canals, once in rank order and once in map order", () => {
  const data = fake(), { simScope } = logic(data);
  const x = simScope([data.X]);
  assert.deepStrictEqual(names(x.canals), ["A", "B"]);                     // the drain is left out
  assert.deepStrictEqual(names(x.canalsUnranked), ["B", "A"]);
  assert.deepStrictEqual(x.ids, [0]);
  assert.deepStrictEqual(names(simScope([data.X, data.Y]).canals), ["A", "B", "C", "D"]);
});

test("simScope: demand and revenue at stake are the published figures times the share of valley canal km", () => {
  const data = fake(), { simScope } = logic(data);
  const x = simScope([data.X]);                                            // 30 km of the valley's 30 km
  assert.strictEqual(x.share, 1);
  assert.strictEqual(x.demandAf, 10);
  assert.strictEqual(x.revenueAtStake, 1000);
  assert.strictEqual(x.outsideValley, false);
  assert.strictEqual(x.members, 1);
  const xy = simScope([data.X, data.Y]);                                   // 40 km against the valley's 30
  close(xy.share, 40 / 30);
  close(xy.demandAf, 10 * 40 / 30);
  assert.strictEqual(xy.outsideValley, true);
  assert.strictEqual(xy.members, 2);
});

test("simScope: today's chance is the frozen model's, weighted by canal km, with the district's own forecast as the fallback", () => {
  const data = fake(), { simScope } = logic(data);
  close(simScope([data.X]).pNow, 0.4);                                     // county A has a live value; B has none
  close(simScope([data.Y]).pNow, 0.2);                                     // no live value: the district's pSeason
  close(simScope([data.X, data.Y]).pNow, (0.4 * 30 + 0.2 * 10) / 40);      // 0.35
});

test("simScope: an El Paso district reads the Elephant Butte reservoir record", () => {
  const data = fake(), s = logic(data).simScope([data.Z]);
  assert.strictEqual(s.system, "Elephant Butte");
  assert.deepStrictEqual(s.weeks.map((w) => w.pct), [10, 11, 12, 13, 14, 15]);
  assert.strictEqual(L.usesElephantButte(data.Z), true);
  assert.strictEqual(L.usesElephantButte(data.X), false);
  assert.strictEqual(L.usesElephantButte({ fips: [] }), false);
  assert.strictEqual(L.usesElephantButte({ fips: ["48141", "A"] }), false);   // every county must draw on it
});

test("simScope: an empty list gives every week, no canals and nothing at stake", () => {
  const s = logic().simScope([]);
  assert.strictEqual(s.weeks.length, 6);
  assert.deepStrictEqual([s.canals.length, s.share, s.demandAf, s.pNow, s.members], [0, 0, 0, 0, 0]);
});

test("simScope: without the frozen model there are no forecasts and today's chance is the district's own", () => {
  const data = fake(); delete data.SIM.pre2020;
  const s = logic(data).simScope([data.X]);
  assert.ok(s.weeks.every((w) => w.forecast === null));
  close(s.pNow, 0.6);
});

test("simScope output runs through the engine", () => {
  const data = fake(), run = E.simulate(logic(data).simScope([data.X, data.Y]), { trigger: "always" }, { budget: 1e6 });
  assert.strictEqual(run.plan.canals, 4);
  assert.strictEqual(run.years.length, 2);                                 // 2019 and 2020
});

/* ---------- hitRates ---------- */
test("hitRates: recall as published, and false alarms as a share of the seasons that were not droughts", () => {
  // The frozen model's test: 10 false alarms in 100 - 60 = 40 seasons with no drought.
  assert.deepStrictEqual(logic().hitRates(), { recall: 0.9, falseAlarm: 0.25 });
});

test("hitRates falls back to the pipeline's trigger test when there is no frozen model, and never divides by zero", () => {
  const data = fake(); delete data.SIM.pre2020;
  // 20 rows, 20 drought seasons: no season without a drought, so the divisor is held at 1.
  assert.deepStrictEqual(logic(data).hitRates(), { recall: 0.8, falseAlarm: 5 });
  data.HG.trigger.rows = 45;
  assert.deepStrictEqual(logic(data).hitRates(), { recall: 0.8, falseAlarm: 0.2 });
});

/* ---------- The real data files ---------- */
// data/core.js and data/sim.js set window.HG and window.HG_SIM. They are read, never written.
function realData() {
  const window = {};
  for (const file of ["core.js", "sim.js"]) {
    new Function("window", fs.readFileSync(path.join(__dirname, "..", "data", file), "utf8"))(window);
  }
  // The canal fields the plan needs, by their position in the generated list (see js/common.js).
  const canals = window.HG.canals.map((c, i) => ({ id: i, km: c[4], rate: c[5], district: c[7], rank: c[8], usd: c[9] }));
  return { HG: window.HG, SIM: window.HG_SIM, canals, published: { worstCaseRevenue: 1, valleyIrrigationAf: 1 } };
}

test("real data: the plan for the pipeline's example budget equals the pipeline's published totals", () => {
  const data = realData(), published = data.HG.plan;
  const inDistricts = data.canals.filter((c) => c.district >= 0);
  const plan = L.makeLogic(data).planFor(inDistricts, published.budget_usd, null);
  assert.ok(plan.funded.length > 0);
  assert.strictEqual(Math.round(plan.spent), published.spent_usd);
  assert.strictEqual(Math.round(plan.km * 10) / 10, published.sealed_km);
  assert.strictEqual(Math.round(plan.savedLow), published.saved_af_low);
  assert.strictEqual(Math.round(plan.savedHigh), published.saved_af_high);
  assert.strictEqual(Math.round(plan.costAll), published.cost_to_treat_everything_usd);
  assert.ok(plan.spent <= published.budget_usd);
});

test("real data: simScope lines every district's weeks up with the weekly record", () => {
  const data = realData(), { simScope } = L.makeLogic(data);
  for (const d of [data.HG.districts[0], data.HG.districts[data.HG.districts.length - 1]]) {
    const s = simScope([d]);
    assert.strictEqual(s.weeks.length, data.SIM.nWeeks);
    assert.strictEqual(s.weeks[0].date, data.SIM.week0);
    assert.strictEqual(s.weeks[s.weeks.length - 1].pct, data.SIM.reservoirs[s.system][data.SIM.nWeeks - 1]);
    for (let i = 1; i < s.weeks.length; i++) assert.strictEqual(Date.parse(s.weeks[i].date) - Date.parse(s.weeks[i - 1].date), 7 * 864e5);
  }
});

/* ---------- The replay of real years ---------- */
// Weekly data from Tuesday 2007-01-02: 2007, 2008 and 2009 whole, 2010 cut off after 30 weeks.
// County A has a forecast on the first week of each month from January 2008 to December 2009.
function replayFake(change) {
  const data = fake(), nWeeks = 52 * 3 + 30, start = Date.parse("2007-01-02T12:00:00Z");
  const dateOf = (i) => new Date(start + i * 7 * 864e5);
  const forecastA = [], seen = {};
  for (let i = 0; i < nWeeks; i++) {
    const d = dateOf(i), key = d.getUTCFullYear() + "-" + d.getUTCMonth(), year = d.getUTCFullYear();
    const first = !seen[key]; seen[key] = true;
    // 2008: a warning from March on. 2009: no warning all year.
    forecastA.push(first && (year === 2008 || year === 2009) ? (year === 2008 && d.getUTCMonth() >= 2 ? 0.6 : 0.1) : null);
  }
  data.SIM = {
    week0: "2007-01-02", nWeeks, valley: ["A"],
    cls: { A: "0".repeat(nWeeks), B: "0".repeat(nWeeks), C: "0".repeat(nWeeks), "48141": "0".repeat(nWeeks) },
    reservoirs: { "Amistad-Falcon": Array.from({ length: nWeeks }, () => 30), "Elephant Butte": Array.from({ length: nWeeks }, () => 30) },
    forecast: { A: forecastA },
    pre2020: null,
  };
  data.published = { worstCaseRevenue: 1e6, valleyIrrigationAf: 10 };      // $100,000 an acre-foot, so sealing can pay
  data.dateOf = dateOf;
  if (change) change(data);
  return data;
}

test("replayScope keeps only whole years that have forecasts, and says which", () => {
  const data = replayFake(), s = logic(data).replayScope([data.X]);
  assert.strictEqual(s.firstYear, 2008);                                   // 2007 has no forecast
  assert.strictEqual(s.lastYear, 2009);                                    // 2010 stops after 30 weeks
  assert.deepStrictEqual(Array.from(new Set(s.weeks.map((w) => w.year))), [2008, 2009]);
  assert.strictEqual(s.weeks.length, 53 + 52);                              // 2008 has 53 Tuesdays
  assert.strictEqual(s.weeks[0].date, "2008-01-01");
  assert.deepStrictEqual(names(s.canals), ["A", "B"]);                     // the same canals as the simulation's scope
});

test("replayScope gives each week the newest forward-chained forecast made on or before it", () => {
  const data = replayFake(), s = logic(data).replayScope([data.X]);
  const on = (date) => s.weeks.find((w) => w.date === date).forecast;
  assert.strictEqual(on("2008-01-01"), 0.1);                               // made that day
  assert.strictEqual(on("2008-02-26"), 0.1);                               // still February's
  assert.strictEqual(on("2008-03-04"), 0.6);                               // March's, the day it was made
  assert.strictEqual(on("2008-03-25"), 0.6);
  assert.strictEqual(on("2008-12-30"), 0.6);
  assert.strictEqual(on("2009-01-06"), 0.1);                               // a new year's forecast replaces it
  // The value never comes from a later week: every week's forecast was already made by then.
  s.weeks.forEach((w) => {
    let latest = null;
    data.SIM.forecast.A.forEach((p, i) => { if (p != null && data.dateOf(i).toISOString().slice(0, 10) <= w.date) latest = p; });
    assert.strictEqual(w.forecast, latest, w.date);
  });
});

test("replayScope uses the forward-chained forecasts, not the frozen model's", () => {
  const data = replayFake((d) => { d.SIM.pre2020 = { monthly: { A: [["2008-01-01", 0.99, 1]] }, live: {} }; });
  const lg = logic(data);
  assert.ok(lg.replayScope([data.X]).weeks.every((w) => w.forecast !== 0.99));
  assert.ok(lg.simScope([data.X]).weeks.some((w) => w.forecast === 0.99));
});

test("replayScope gives null when the data holds no year with forecasts", () => {
  const none = replayFake((d) => { delete d.SIM.forecast; });
  assert.strictEqual(logic(none).replayScope([none.X]), null);
  const data = replayFake();
  assert.strictEqual(logic(data).replayScope([data.Y]), null);             // county C has no forecast
});

test("replay: five rows in the table's order, each from the engine's own run of that policy", () => {
  const data = replayFake(), scope = logic(data).replayScope([data.X]), over = { budget: 1e6 };
  const result = L.replay(scope, over);
  assert.deepStrictEqual(result.rows.map((r) => r.trigger), ["never", "declared", "d1", "forecast", "always"]);
  assert.deepStrictEqual(result.years, [2008, 2009]);
  assert.deepStrictEqual([result.firstYear, result.lastYear], [2008, 2009]);
  result.rows.forEach((row) => {
    const run = E.simulate(scope, { trigger: row.trigger }, over);
    assert.strictEqual(row.spend, run.totals.spend);
    assert.strictEqual(row.loss, run.totals.loss);
    assert.strictEqual(row.keptAf, run.totals.savedAf);
    assert.strictEqual(row.yearsSealed, run.totals.yearsActed);
  });
});

test("replay: each policy seals in the years its rule says, on a record made up to tell them apart", () => {
  // No drought class at all (so no declaration and no D1), a forecast warning in 2008 only, and
  // reservoirs at 30% throughout (a shortage every season).
  const data = replayFake(), result = L.replay(logic(data).replayScope([data.X]), { budget: 1e6 });
  const sealed = {}; result.rows.forEach((r) => { sealed[r.trigger] = r.sealedYears; });
  assert.deepStrictEqual(sealed, { never: [], declared: [], d1: [], forecast: [2008], always: [2008, 2009] });
  const by = {}; result.rows.forEach((r) => { by[r.trigger] = r; });
  assert.strictEqual(by.never.spend, 0);
  assert.strictEqual(by.never.saving, 0);
  assert.strictEqual(by.d1.loss, by.never.loss);
  close(by.always.spend, 2 * by.forecast.spend);
  assert.ok(by.forecast.loss < by.never.loss && by.always.loss < by.forecast.loss);
  // Saving is crop loss avoided minus sealant spent.
  close(by.forecast.saving, by.never.loss - by.forecast.loss - by.forecast.spend);
});

test("replay: a row's totals are the sums of its per-year results", () => {
  const data = replayFake(), result = L.replay(logic(data).replayScope([data.X]), { budget: 1e6 });
  result.rows.forEach((row) => {
    const sum = (key) => row.perYear.reduce((s, y) => s + y[key], 0);
    assert.deepStrictEqual(row.perYear.map((y) => y.year), [2008, 2009]);
    close(row.spend, sum("spend")); close(row.loss, sum("loss")); close(row.keptAf, sum("keptAf")); close(row.usedAf, sum("usedAf"));
    assert.strictEqual(row.yearsSealed, row.perYear.filter((y) => y.sealed).length);
  });
});

/* A replay result written by hand, to test the sentence on its own. cost = loss + spend. */
function handResult(d1, forecast, always) {
  const row = (trigger, r) => Object.assign({ trigger, yearsSealed: r.sealedYears.length }, r);
  return { years: [2008, 2009, 2010, 2011], rows: [
    row("never", { sealedYears: [], cost: 1000000 }), row("declared", { sealedYears: [2009], cost: 950000 }),
    row("d1", d1), row("forecast", forecast), row("always", always)] };
}

test("replaySentence says the forecast came out ahead only when its modelled total cost is lower", () => {
  const s = L.replaySentence(handResult({ sealedYears: [2008, 2009, 2010], cost: 800000 }, { sealedYears: [2008, 2009], cost: 600000 }, { sealedYears: [2008, 2009, 2010, 2011], cost: 700000 }));
  assert.strictEqual(s.vsD1, "better");
  assert.strictEqual(s.vsAlways, "better");
  assert.strictEqual(s.text, "In this replay, acting on the forecast sealed in 2 of 4 years. The forecast ended $200k ahead of the D1 rule (3 years sealed) in modelled total cost. " +
    "The forecast ended $100k ahead of sealing every year (4 years sealed) in modelled total cost.");
});

test("replaySentence says the forecast came out behind when its modelled total cost is higher", () => {
  const s = L.replaySentence(handResult({ sealedYears: [2008], cost: 500000 }, { sealedYears: [2008, 2009], cost: 600000 }, { sealedYears: [2008, 2009, 2010, 2011], cost: 450000 }));
  assert.strictEqual(s.vsD1, "worse");
  assert.strictEqual(s.vsAlways, "worse");
  assert.ok(s.text.indexOf("The forecast ended $100k behind the D1 rule (1 year sealed) in modelled total cost.") > 0, s.text);
  assert.ok(s.text.indexOf("The forecast ended $150k behind sealing every year (4 years sealed) in modelled total cost.") > 0, s.text);
  assert.ok(s.text.indexOf("ahead") < 0);
});

test("replaySentence says the two gave the same result when they sealed in the same years at the same cost", () => {
  const s = L.replaySentence(handResult({ sealedYears: [2008, 2010], cost: 600000 }, { sealedYears: [2008, 2010], cost: 600000 }, { sealedYears: [2008, 2009, 2010, 2011], cost: 550000 }));
  assert.strictEqual(s.vsD1, "same");
  assert.strictEqual(s.vsAlways, "worse");
  assert.ok(s.text.indexOf("The forecast and the D1 rule sealed in the same 2 years and gave the same modelled result.") > 0, s.text);
});

test("replaySentence calls a gap under 0.2% of the total level, and gives the gap", () => {
  const s = L.replaySentence(handResult({ sealedYears: [2008], cost: 600900 }, { sealedYears: [2008, 2009], cost: 600000 }, { sealedYears: [2008, 2009, 2010, 2011], cost: 598900 }));
  assert.strictEqual(s.vsD1, "same");
  assert.strictEqual(s.vsAlways, "same");
  assert.ok(s.text.indexOf("The forecast ended about level with the D1 rule (1 year sealed): the modelled totals differ by $900.") > 0, s.text);
  // Just over the line it is no longer level.
  assert.strictEqual(L.replaySentence(handResult({ sealedYears: [2008], cost: 601300 }, { sealedYears: [2008, 2009], cost: 600000 }, { sealedYears: [], cost: 600000 })).vsD1, "better");
});

test("replaySentence can go each way for the two comparisons at once, and mixes them correctly", () => {
  const s = L.replaySentence(handResult({ sealedYears: [2008, 2009, 2010], cost: 800000 }, { sealedYears: [2008, 2009], cost: 600000 }, { sealedYears: [2008, 2009, 2010, 2011], cost: 500000 }));
  assert.deepStrictEqual([s.vsD1, s.vsAlways], ["better", "worse"]);
});

test("replaySentence built from the engine: a forecast that warns in the dry year beats a rule that never fires", () => {
  const data = replayFake(), s = L.replaySentence(L.replay(logic(data).replayScope([data.X]), { budget: 1e6 }));
  assert.strictEqual(s.vsD1, "better");                                    // D1 never sealed; the forecast sealed in 2008 and it paid
  assert.strictEqual(s.vsAlways, "worse");                                 // sealing in 2009 too would also have paid
});

test("real data: the replay holds its invariants for one district and for the whole state view", () => {
  const data = realData(), lg = L.makeLogic(data);
  const hasCanals = (d) => data.canals.some((c) => c.district === data.HG.districts.indexOf(d) && c.rank != null);
  const stateView = data.HG.districts.filter((d) => hasCanals(d) && !L.usesElephantButte(d));
  const oneDistrict = [data.HG.districts.find(hasCanals)];
  for (const members of [oneDistrict, stateView]) {
    const scope = lg.replayScope(members), over = { budget: scope.canals.reduce((s, c) => s + c.usd, 0) + 1 };
    const result = L.replay(scope, over), by = {};
    result.rows.forEach((r) => { by[r.trigger] = r; });
    // The years: from the first forward-chained forecast to the last whole year, with none missing.
    assert.strictEqual(result.firstYear, 2008);
    assert.ok(result.lastYear >= 2025);
    assert.deepStrictEqual(result.years, Array.from({ length: result.lastYear - 2007 }, (x, i) => 2008 + i));
    assert.ok(scope.weeks.every((w) => w.pct != null && w.cls != null), "real reservoir levels and drought classes for every week");
    assert.ok(scope.weeks.every((w) => w.forecast != null), "a forecast for every week");
    // Doing nothing spends nothing and keeps nothing.
    assert.deepStrictEqual([by.never.spend, by.never.keptAf, by.never.yearsSealed, by.never.saving], [0, 0, 0, 0]);
    // Sealing every year seals in every year, and no other policy seals in more.
    assert.strictEqual(by.always.yearsSealed, result.years.length);
    for (const t of ["declared", "d1", "forecast"]) {
      assert.ok(by[t].yearsSealed <= by.always.yearsSealed);
      assert.ok(by[t].spend <= by.always.spend);
      assert.ok(by[t].sealedYears.every((y) => by.always.sealedYears.indexOf(y) >= 0));
    }
    // Totals are the sums of the engine's per-year results.
    result.rows.forEach((row) => {
      const run = E.simulate(scope, { trigger: row.trigger }, over), sum = (key) => run.years.reduce((s, y) => s + y[key], 0);
      close(row.spend, sum("spend")); close(row.loss, sum("loss")); close(row.keptAf, sum("savedAf"));
      assert.strictEqual(row.yearsSealed, run.years.filter((y) => y.acted).length);
      close(row.saving, by.never.loss - row.loss - row.spend);
      assert.ok(row.loss <= by.never.loss + 1e-6);                         // sealing never adds to crop loss
      assert.ok(row.usedAf <= row.keptAf + 1e-9);
    });
    // The same inputs give the same result.
    assert.deepStrictEqual(L.replay(lg.replayScope(members), over), result);
    const sentence = L.replaySentence(result);
    assert.ok(["better", "same", "worse"].indexOf(sentence.vsD1) >= 0 && ["better", "same", "worse"].indexOf(sentence.vsAlways) >= 0);
    assert.strictEqual(sentence.vsD1 === "better", by.forecast.cost < by.d1.cost && sentence.vsD1 !== "same");
  }
});

test("the simulation's own scope is unchanged by the replay: it still reads the frozen model's forecasts", () => {
  const data = realData(), lg = L.makeLogic(data), d = data.HG.districts[0];
  const sim = lg.simScope([d]);
  assert.deepStrictEqual(Object.keys(sim), ["weeks", "canals", "canalsUnranked", "demandAf", "revenueAtStake", "share", "system", "pNow", "ids", "outsideValley", "members"]);
  assert.ok(sim.weeks.filter((w) => w.year < 2020).every((w) => w.forecast === null));   // the frozen model starts in 2020
  assert.ok(lg.replayScope([d]).weeks.filter((w) => w.year < 2020).every((w) => w.forecast !== null));
});
