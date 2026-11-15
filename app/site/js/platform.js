/*
  platform.js: the platform (app.html).

  HOW IT IS ORGANISED
    state      one object holding every choice the user has made (scope, step, budget ...)
    the map    js/scanmap.js draws it; this file only tells it what to show
    the steps  renderRisk(), renderBudget(), renderSim() each fill the right-hand panel
    refresh()  updates the map and the current step; called after any change of state

  "Scope" means who is looking: one district (state.scope = its number in HG.districts)
  or the whole state (state.scope = -1).

  Every canal decision is shown as the same three numbers: what it COSTS, how long it TAKES
  and how much water it SAVES. They come from U.canalNumbers() in common.js.
*/
(function () {
  "use strict";
  const HG = window.HG, SIM = window.HG_SIM, U = window.HGU, E = window.HGEngine;
  const $ = (id) => document.getElementById(id);
  const STATE = -1;
  const FROZEN = SIM.pre2020;                           // the forecast model trained only on data before 2020
  const ELEPHANT_BUTTE = ["48141", "48229"];           // El Paso and Hudspeth draw on Elephant Butte
  const TODAY = new Date().toISOString().slice(0, 10);
  const SEVERITIES = [                                  // the "what if" drought choices in the budget planner
    { p: null, label: "This week's forecast" },
    { p: 0.25, label: "Moderate (25%)" },
    { p: 0.5, label: "Severe (50%)" },
    { p: 0.8, label: "Extreme (80%)" },
  ];
  const SHOCKS = [                                      // "what if" blows the simulation can add; sizes are our assumptions
    { key: "mexico", label: "Mexico misses a delivery", note: "storage drops 8 points in the first spring", shock: { year: 1, month: 3, points: -8 } },
    { key: "dry2", label: "A second dry year", note: "the second season is also drawn from dry years", secondDryYear: true },
    { key: "wet", label: "A wet autumn", note: "storage gains 10 points next October", shock: { year: 1, month: 10, points: 10 } },
  ];

  const state = { scope: null, step: "risk", mapMode: "now", budget: null, severity: null, simMode: "today",
                  overrides: {}, county: null, canal: null, live: null, shocks: {} };

  /* ---------- Scope helpers ---------- */
  const district = () => (state.scope >= 0 ? HG.districts[state.scope] : null);
  const scopeCanals = () => (state.scope >= 0 ? U.canals.filter((c) => c.district === state.scope)
                                              : U.canals.filter((c) => c.district >= 0));
  const scopeName = () => (district() ? district().name : "State of Texas");
  const usesElephantButte = (d) => d.fips.length > 0 && d.fips.every((f) => ELEPHANT_BUTTE.indexOf(f) >= 0);
  const params = () => E.makeParams(state.overrides);
  /* The chance of a drought season used by the planner: the "what if" value, or the forecast. */
  function scopeP() {
    if (state.severity != null) return state.severity;
    if (district()) return district().pSeason;
    const km = HG.districts.reduce((s, d) => s + d.canalKm, 0);       // state view: weighted by canal km
    return HG.districts.reduce((s, d) => s + d.pSeason * d.canalKm, 0) / km;
  }
  function scopeP0() { const keep = state.severity; state.severity = null; const p = scopeP(); state.severity = keep; return p; }
  function reservoirFor(d) {
    const name = d && usesElephantButte(d) ? "Elephant Butte" : "Amistad-Falcon";
    const county = HG.river.find((c) => c.reservoir === name);
    let pct = county ? county.reservoirPct : null, date = HG.week, live = false;
    if (state.live && state.live.systems && state.live.systems[name]) {
      pct = state.live.systems[name].pct; date = state.live.systems[name].date; live = true;
    }
    return { name, pct, date, live };
  }

  /* ---------- Small HTML pieces ---------- */
  const kpi = (label, value, small) => '<div class="kpi"><span>' + label + "</span><b>" + value + "</b>" + (small ? "<small>" + small + "</small>" : "") + "</div>";
  const chip = (tier, text) => '<span class="chip ' + tier + '"><i></i>' + (text || tier) + "</span>";
  const af = (n) => U.num(n.afLow) + " to " + U.num(n.afHigh);
  const afMid = (n) => U.num((n.afLow + n.afHigh) / 2, (n.afLow + n.afHigh) / 2 < 10 ? 1 : 0);
  const money = (v) => (v < 0 ? "-" + money(-v) : v >= 1e9 ? "$" + (v / 1e9).toFixed(2) + "B" : v >= 1e6 ? "$" + (v / 1e6).toFixed(v >= 1e8 ? 0 : 1) + "M" : v >= 1e4 ? "$" + Math.round(v / 1e3) + "k" : "$" + U.num(v));
  /* The three big numbers. n = U.canalNumbers(...). oneCrew = show the time for a single crew. */
  function triple(n, oneCrew, cls) {
    const p = params(), days = oneCrew ? n.crewDays : n.days;
    return '<div class="triple ' + (cls || "") + '">' +
      "<div><span>Costs</span><b>" + (n.usd >= 1e6 ? money(n.usd) : U.usd(n.usd)) + "</b><small>sealant materials, " + U.num(n.km, n.km < 10 ? 2 : 1) + " km. Labour is extra.</small></div>" +
      '<div class="time"><span>Takes</span><b>' + U.workTime(days) + "</b><small>of work for " + (oneCrew ? "one crew" : p.crews + (p.crews === 1 ? " crew" : " crews")) + " at " + p.kmPerCrewDay + " km a day (our assumption)</small></div>" +
      '<div class="save"><span>Saves</span><b>' + (n.afHigh > 0 ? af(n) : "unknown") + "</b><small>" + (n.afHigh > 0 ? "acre-feet in one 90-day application. Worth " + money(n.worthLow) + " to " + money(n.worthHigh) + " to farms in a shortage." : "no seepage rate is published for this soil") + "</small></div></div>";
  }
  function gauge(p) {
    const tier = U.tierFor(p);
    return '<div class="gauge"><i style="width:' + Math.min(100, p * 100) + "%;background:" + U.TIER_COLOR[tier] + '"></i><u style="left:' + HG.threshold * 100 + '%"></u></div>' +
      '<div class="small muted">Warning line at ' + U.pct(HG.threshold) + ". Above it, our test caught " + Math.round(HG.trigger.rules[0].recall * 100) + "% of drought seasons.</div>";
  }
  function canalFacts(c) {
    return (c.kind || "Canal or ditch") + " · " + (c.soil ? c.soil + " soil" : "soil not looked up") +
      (c.rate != null ? " · leaks " + c.rate + " gal per sq ft a day" : "") + " · " + c.level + " · source: " + c.source;
  }
  /* The card for one canal segment: what it is, then cost, time and saving. */
  function canalCard(c) {
    const n = U.canalNumbers([c], params());
    return '<div class="card" style="border-color:var(--blue)"><button class="back" data-act="closeCanal">&times; Close canal</button>' +
      '<div style="display:flex;justify-content:space-between;gap:10px;align-items:baseline"><b style="font-size:1.1rem">' + U.esc(c.name) + "</b>" +
      (c.rank != null ? '<span class="chip">Sealing rank ' + U.num(c.rank) + "</span>" : "") + "</div>" +
      '<div class="small muted">' + U.esc(canalFacts(c)) + (c.district >= 0 ? " · " + U.esc(HG.districts[c.district].name) : "") + "</div>" +
      (c.piped ? '<p class="note" style="margin:10px 0 0">OpenStreetMap maps most of this stretch as piped or culverted. A pipe does not seep, so check it on the ground before spending on it.</p>' : "") +
      (c.rank == null ? '<p class="note" style="margin:10px 0 0">Not in the sealing plan: ' + (c.level === "Drain" ? "it is a drain, which is meant to carry water away." : "no soil reading, so there is no seepage rate to rank it by.") + "</p>" : "") +
      triple(n, true, "small") + "</div>";
  }
  function countyCard(fips, closable) {
    const c = U.countyByFips[fips], river = U.riverByFips[fips];
    const captions = { county: "Aerial view", drought: "Driest area, close-up", ground: "On the ground" };
    const photos = c.photos.map((kind) => '<figure><img loading="lazy" src="' + U.photo(fips, kind) + '" alt="' + captions[kind] + " of " + U.esc(c.name) + ' County"><figcaption>' + captions[kind] + "</figcaption></figure>").join("");
    let credit = "Aerial images: USGS The National Map (public domain), from past flights.";
    if (c.credit && c.photos.indexOf("ground") >= 0) {
      credit += ' Ground photo: <a href="' + U.esc(c.credit.source) + '" target="_blank" rel="noopener">' + U.esc(c.credit.what || "photo") + "</a> by " + U.esc(c.credit.by) + ", " + U.esc(c.credit.licence) + ".";
    }
    return '<div class="card">' +
      (closable ? '<button class="back" data-act="closeCounty">&times; Close county</button>' : "") +
      '<div style="display:flex;justify-content:space-between;gap:10px;align-items:baseline"><b style="font-size:1.05rem">' + U.esc(c.name) + " County</b>" +
      (river ? chip(river.tier, river.tier + " · " + U.pct(river.pSeason)) : "") + "</div>" +
      '<div class="small muted" style="margin:2px 0 8px">Drought now: ' + (c.dm == null ? "no data" : U.DM_TEXT[c.dm]) +
      (c.pop ? " · Population (2020): " + U.num(c.pop) : "") +
      (river ? " · Expected drought weeks in the next year: " + river.weeksLow + " to " + river.weeksHigh : " · Not a river county, so no forecast") + "</div>" +
      (photos ? '<div class="photos">' + photos + "</div>" : "") +
      (c.about ? '<p class="small" style="margin:0 0 4px">' + U.esc(c.about) + ' <a href="' + U.esc(c.page) + '" target="_blank" rel="noopener">Wikipedia</a></p>' : "") +
      '<div class="credit">' + credit + "</div></div>";
  }
  function issuesFor(d) {
    if (!HG.issues) return "";
    const list = HG.issues.issues.filter((x) => (d ? x.district === d.name || (x.where || []).some((f) => d.fips.indexOf(f) >= 0) : true)).slice(0, d ? 6 : 8);
    if (!list.length) return "";
    return "<h3>Open issues from live data</h3><div class=\"card\">" + list.map((x) =>
      '<div class="issue"><span class="sev ' + x.severity + '"></span><div><b>' + U.esc(x.title) + "</b><br><span class=\"muted\">" + U.esc(x.detail) + "</span><br><span class=\"credit\">Source: " + U.esc(x.source) + " · as of " + U.esc(x.as_of) + "</span></div></div>").join("") +
      '</div><p class="credit">' + U.esc(HG.issues.note) + "</p>";
  }
  function mixBar(list, keyOf, colorOf) {
    const total = {}, km = list.reduce((s, c) => s + c.km, 0) || 1;
    list.forEach((c) => { total[keyOf(c)] = (total[keyOf(c)] || 0) + c.km; });
    const keys = Object.keys(total).sort((a, b) => total[b] - total[a]);
    return '<div class="stack">' + keys.map((k) => '<i title="' + U.esc(k) + '" style="width:' + (100 * total[k] / km) + "%;background:" + colorOf(k) + '"></i>').join("") + "</div>" +
      '<div class="legend">' + keys.slice(0, 6).map((k) => '<span><i style="background:' + colorOf(k) + '"></i>' + U.esc(k) + " " + U.num(total[k]) + " km</span>").join("") + "</div>";
  }
  /* One line that says how many canals there are and where the list came from. */
  function canalCount(list) {
    const osm = list.filter((c) => c.source === "OpenStreetMap").length, piped = list.filter((c) => c.piped).length;
    return U.num(list.length) + " canal segments, " + U.num(list.reduce((s, c) => s + c.km, 0)) + " km: " + U.num(list.length - osm) + " from the USGS map" +
      (osm ? " and " + U.num(osm) + " more that only OpenStreetMap has" : "") + ". " + U.num(list.filter((c) => c.name !== "Unnamed canal").length) + " carry a name" +
      (piped ? "; " + U.num(piped) + " are mapped as piped" : "") + ".";
  }
  /* Segments that share a name are one canal. Returns the named canals, longest first, with their numbers. */
  function namedCanals(list) {
    const by = {};
    list.forEach((c) => { if (c.name !== "Unnamed canal") (by[c.name] = by[c.name] || []).push(c); });
    return Object.keys(by).map((name) => ({ name, segs: by[name], n: U.canalNumbers(by[name].filter((c) => c.rank != null), params()), km: by[name].reduce((s, c) => s + c.km, 0) }))
      .sort((a, b) => b.km - a.km);
  }

  /* ---------- The map ---------- */
  const map = window.HGMap.create({
    stage: $("stage"), canvas: $("map"), tip: $("tip"), coords: $("coords"), bar: $("bar"),
    hud: { phase: $("phase"), line1: $("hud1"), line2: $("hud2") },
    onCanal: (c) => { state.canal = c.id; if (state.step === "sim") state.step = "risk"; refresh(false); },
    onDistrict: (i) => setScope(i),
    onCounty: (fips) => { state.county = fips; state.canal = null; state.step = "risk"; refresh(false); },
    tipHtml(hit) {
      if (hit.canal) {
        const c = hit.canal, n = U.canalNumbers([c], params());
        return "<b>" + U.esc(c.name) + "</b><dl><dt>Costs</dt><dd class=\"big\">" + U.usd(n.usd) + "</dd><dt>Takes</dt><dd class=\"big\">" + U.workTime(n.crewDays) + "</dd><dt>Saves</dt><dd class=\"big\">" + (n.afHigh > 0 ? af(n) + " acre-feet" : "unknown") + "</dd>" +
          "<dt>Length</dt><dd>" + U.num(c.km, 2) + " km</dd><dt>Soil</dt><dd>" + U.esc(c.soil || "not looked up") + "</dd><dt>Class</dt><dd>" + U.esc(c.level) + "</dd></dl>" +
          "<small>" + U.esc((c.kind || "Canal or ditch") + (c.piped ? ", mapped as piped" : "") + ". Click for the full card.") + "</small>";
      }
      if (hit.district != null) { const d = HG.districts[hit.district]; return "<b>" + U.esc(d.name) + "</b><dl><dt>Risk</dt><dd>" + d.risk + ", " + U.pct(d.pSeason) + "</dd><dt>Canals</dt><dd>" + U.num(d.canalKm) + " km</dd></dl><small>Click to open this district.</small>"; }
      const c = U.countyByFips[hit.county], river = U.riverByFips[hit.county];
      return "<b>" + U.esc(c.name) + " County</b><dl><dt>Drought now</dt><dd>" + (c.dm == null ? "no data" : U.DM_TEXT[c.dm]) + "</dd>" +
        (river ? "<dt>6-month chance</dt><dd>" + U.pct(river.pSeason) + ", " + river.tier + "</dd>" : "") + "</dl><small>Click for photos and a profile.</small>";
    },
  });
  function legend() {
    const forecast = state.mapMode === "forecast", plan = state.step === "budget";
    const key = (color, text) => '<span><i style="background:' + color + '"></i>' + text + "</span>";
    $("legend").innerHTML =
      '<div class="modes"><button data-mode="now" class="' + (forecast ? "" : "on") + '">Drought now</button><button data-mode="forecast" class="' + (forecast ? "on" : "") + '">6-month forecast</button></div>' +
      (forecast ? "<h4>River counties: chance of a drought season</h4><div class=\"keys\">" + ["Low", "Watch", "Warning"].map((t) => key(U.TIER_COLOR[t], t)).join("") + "</div>"
                : "<h4>Drought Monitor, week of " + U.niceDate(HG.week) + '</h4><div class="ramp">' + HG.dmLabels.map((l, i) => '<span><i style="background:' + U.DM_COLOR[i] + '"></i>' + l + "</span>").join("") + "</div>") +
      "<h4>Canals (" + U.num(scopeCanals().length) + " segments here)</h4><div class=\"keys\">" +
      (plan ? key("var(--fund)", "Sealed by this budget") + key("var(--muted)", "Not funded") : HG.levels.map((l) => key(U.LEVEL_COLOR[l], l)).join("")) + "</div>";
  }
  $("legend").addEventListener("click", (e) => { const mode = e.target.dataset.mode; if (mode) { state.mapMode = mode; syncMap(); } });
  $("views").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; if (b.dataset.view === "scope") map.fitScope(); else map.flyTo(b.dataset.view); });
  $("zin").onclick = () => map.zoom(1.6); $("zout").onclick = () => map.zoom(1 / 1.6);
  $("replay").onclick = () => map.runScan(); $("skip").onclick = () => map.skip();
  function syncMap() {
    const lakes = {};
    if (state.live && state.live.systems && state.live.systems["Elephant Butte"]) lakes["Elephant Butte"] = state.live.systems["Elephant Butte"].pct;
    map.set({ mode: state.mapMode, scope: state.scope, county: state.county, canal: state.canal,
              funded: state.step === "budget" ? currentPlan().fundedIds : null, lakes });
    legend();
  }

  /* ---------- The budget plan for the current scope, budget and severity ---------- */
  let planCache = null, planKey = "";
  function currentPlan() {
    const k = [state.scope, state.budget, state.severity].join("|");
    if (k !== planKey) { planCache = U.planFor(scopeCanals(), state.budget, state.severity); planKey = k; }
    return planCache;
  }
  const costAll = () => U.planFor(scopeCanals(), 0, null).costAll;
  function defaultBudget() {
    const all = costAll();
    if (state.scope === STATE) return Math.min(all, HG.plan.budget_usd);
    return Math.max(100, Math.round(all * 0.25 / 100) * 100);
  }
  const maxBudget = () => Math.max(100, Math.ceil(costAll() / 100) * 100);
  const budgetStep = () => (maxBudget() > 200000 ? 5000 : maxBudget() > 20000 ? 500 : 100);
  /* The two sliders behind "how long it takes". Used on the budget step and the simulation step. */
  function crewFields() {
    const p = params();
    return '<div class="field"><label for="a_crews"><span>Crews working at once <span class="tag assumption">assumption</span></span><output id="o_crews">' + p.crews + '</output></label><input type="range" data-param="crews" id="a_crews" min="1" max="10" step="1" value="' + p.crews + '"></div>' +
      '<div class="field"><label for="a_kmPerCrewDay"><span>Canal one crew seals in a day <span class="tag assumption">assumption</span></span><output id="o_kmPerCrewDay">' + p.kmPerCrewDay + ' km</output></label><input type="range" data-param="kmPerCrewDay" id="a_kmPerCrewDay" min="1" max="20" step="1" value="' + p.kmPerCrewDay + '"></div>';
  }

  /* ---------- Step 1: Risk profile ---------- */
  function renderRisk() {
    const d = district(), list = scopeCanals(), res = reservoirFor(d);
    let html = "";
    if (state.canal != null) html += canalCard(U.canals[state.canal]);
    if (state.county && !d) html += countyCard(state.county, true);
    if (d) {
      const act = U.actionFor(d.pSeason);
      const worst = Math.max.apply(null, d.fips.map((f) => U.countyByFips[f].dm || 0));
      const treatable = list.filter((c) => c.rank != null), all = U.canalNumbers(treatable, params());
      const named = namedCanals(list);
      html += '<button class="back" data-act="state">&larr; All of Texas</button>' +
        "<h2>" + U.esc(d.name) + "</h2><div class=\"sub\">" + U.esc(d.kind) + " · " + d.counties.join(" and ") + " County · " + chip(d.risk) + "</div>" +
        '<div class="card"><div style="display:flex;justify-content:space-between;align-items:baseline"><b>Chance of a drought season in the next 6 months</b><b class="bigNum">' + U.pct(d.pSeason) + "</b></div>" + gauge(d.pSeason) + "</div>" +
        '<div class="card action ' + act.key + '"><span class="small muted">Recommended now</span><b>' + act.title + "</b>" + act.text + "</div>" +
        '<div class="kpis">' +
          kpi("Drought now", U.DM_TEXT[worst].split(" ")[0] === "No" ? "None" : U.DM_TEXT[worst].split(" ")[0], U.DM_TEXT[worst]) +
          kpi(res.name + " reservoirs", res.pct == null ? "n/a" : res.pct + "% full", (res.live ? "Live reading, " : "Saved reading, ") + U.niceDate(res.date)) +
        "</div>" +
        "<h3>If you sealed every treatable canal in this district</h3>" + (treatable.length ? triple(all) : '<p class="note">No canal here can be ranked: they are drains, or sit on soil with no published seepage rate.</p>') +
        '<p class="credit">' + canalCount(list) + " " + U.num(treatable.length) + " can be ranked and priced.</p>" +
        '<div class="rowBtns"><button class="btn" data-act="go" data-step="budget">Choose a budget and see which canals &rarr;</button></div>' +
        "<h3>Canals by priority</h3><div class=\"card\">" + mixBar(list, (c) => c.level, (k) => U.LEVEL_COLOR[k]) + '<p class="credit" style="margin:8px 0 0">' + U.esc(HG.levelRule) + "</p></div>" +
        "<h3>Canals by soil</h3><div class=\"card\">" + mixBar(list, (c) => c.soil || "Not looked up", (k) => { const r = HG.seepage[k]; return r == null ? U.LEVEL_COLOR["Unknown soil"] : r >= 7.48 ? U.TIER_COLOR.Warning : r >= 2.9 ? U.TIER_COLOR.Watch : U.TIER_COLOR.Low; }) +
          '<p class="credit" style="margin:8px 0 0">Red soils leak fastest. Seepage rates: ' + U.esc(HG.seepageSource) + ".</p></div>" +
        (named.length ? "<h3>Named canals (" + named.length + ")</h3><div class=\"scroll\"><table class=\"t\"><tr><th>Canal</th><th class=\"r\">km</th><th class=\"r\">Costs</th><th class=\"r\">Takes</th><th class=\"r\">Saves (acre-feet)</th></tr>" +
          named.slice(0, 80).map((g) => '<tr class="click" data-act="canal" data-id="' + g.segs[0].id + '"><td><b>' + U.esc(g.name) + "</b><br><span class=\"muted small\">" + g.segs.length + (g.segs.length === 1 ? " segment" : " segments") + "</span></td><td class=\"r\">" + U.num(g.km, 1) + "</td>" +
            (g.n.km > 0 ? '<td class="r cost">' + U.usd(g.n.usd) + '</td><td class="r time">' + U.workTime(g.n.crewDays) + '</td><td class="r save">' + af(g.n) + "</td>" : '<td class="r muted" colspan="3">not rankable</td>') + "</tr>").join("") +
          '</table></div><p class="credit">One crew. Segments that share a name are added up. Click a row to find the canal on the map.</p>' : "") +
        issuesFor(d) +
        "<h3>The " + (d.fips.length > 1 ? "counties" : "county") + " it serves</h3>" + d.fips.map((f) => countyCard(f, false)).join("");
    } else {
      const inDrought = HG.texas.filter((c) => c.dm != null && c.dm >= 2).length;
      const warned = HG.river.filter((c) => c.pSeason >= HG.threshold).length;
      const dWarn = HG.districts.filter((x) => x.risk === "Warning").length;
      const all = U.canalNumbers(list.filter((c) => c.rank != null), params());
      html += "<h2>State of Texas</h2><div class=\"sub\">Drought across all 254 counties, and the " + HG.districts.length + " irrigation and water districts on the Rio Grande. Week of " + U.niceDate(HG.week) + ".</div>" +
        '<div class="kpis">' +
          kpi("Counties in drought now", inDrought + " of 254", "D1 or worse, U.S. Drought Monitor") +
          kpi("River counties over the warning line", warned + " of 14", "6-month forecast at " + U.pct(HG.threshold) + " or more") +
          kpi(res.name + " reservoirs", res.pct == null ? "n/a" : res.pct + "% full", (res.live ? "Live reading, " : "Saved reading, ") + U.niceDate(res.date)) +
          kpi("Districts at Warning", dWarn + " of " + HG.districts.length, U.num(HG.plan.canal_km_in_districts) + " km of canals in all") +
        "</div>" +
        "<h3>If the state sealed every treatable canal in all " + HG.districts.length + " districts</h3>" + triple(all) +
        '<p class="credit">On the map: ' + canalCount(U.canals) + " " + U.num(list.length) + " sit inside a district.</p>" +
        '<div class="rowBtns"><button class="btn" data-act="go" data-step="budget">Split a state budget &rarr;</button></div>' +
        "<h3>Districts, highest risk first</h3><div class=\"scroll\" style=\"max-height:420px\"><table class=\"t\"><tr><th>District</th><th>Risk</th><th class=\"r\">6-month chance</th><th class=\"r\">Canal km</th></tr>" +
        HG.districts.map((x, i) => ({ x, i })).sort((a, b) => b.x.pSeason - a.x.pSeason).map(({ x, i }) =>
          '<tr class="click" data-act="district" data-i="' + i + '"><td><b>' + U.esc(x.name) + "</b><br><span class=\"muted small\">" + x.counties.join(", ") + "</span></td><td>" + chip(x.risk) + '</td><td class="r">' + U.pct(x.pSeason) + '</td><td class="r">' + U.num(x.canalKm) + "</td></tr>").join("") +
        '</table></div><p class="small muted">Click any county on the map for its photos and profile. Zoom in and click a district or a canal to open it.</p>' +
        issuesFor(null);
    }
    html += '<p class="note" style="margin-top:18px">The forecast comes from a random forest model trained on the drought record and re-run on new public data (Drought Monitor weekly, reservoirs daily). In testing it only narrowly beat the simple rule "already in moderate drought", so treat it as months of early warning, not as certainty. Canals come from the USGS map' + (HG.osm ? ", with kind, pipe and name detail and " + U.num(HG.osm.added) + " extra canals from OpenStreetMap" : "") + ". No source says which canals are lined.</p>";
    $("view").innerHTML = html;
  }

  /* ---------- Step 2: Budget plan ---------- */
  function renderBudget() {
    const d = district(), all = costAll();
    $("view").innerHTML =
      (d ? '<button class="back" data-act="state">&larr; All of Texas</button>' : "") +
      "<h2>Budget plan</h2><div class=\"sub\">" + U.esc(scopeName()) + ". Set a budget and a drought severity. You get the exact canals to seal, in order, with what each costs, how long it takes and how much water it saves.</div>" +
      (state.canal != null ? canalCard(U.canals[state.canal]) : "") +
      (all <= 0 ? '<p class="note">No canal in this district is in the sealing plan (its canals are drains or sit on soil with no published seepage rate).</p>' :
      '<div class="card"><div class="field"><label for="budget">Sealing budget <output id="budgetOut"></output></label>' +
      '<input id="budget" type="range" min="0" max="' + maxBudget() + '" step="' + budgetStep() + '" value="' + state.budget + '">' +
      '<div class="small muted">Sealing every treatable canal here would cost ' + U.usd(all) + " in sealant materials.</div></div>" +
      '<div class="field"><label>Drought severity to plan for</label><div class="seg" id="sev">' +
      SEVERITIES.map((s) => '<button data-p="' + (s.p == null ? "" : s.p) + '" class="' + (state.severity === s.p ? "on" : "") + '">' + s.label + (s.p == null ? " (" + U.pct(scopeP0()) + ")" : "") + "</button>").join("") +
      "</div></div>" + crewFields() + "</div><div id=\"budgetResult\"></div>");
    if (all > 0) renderBudgetResult();
  }
  function renderBudgetResult() {
    const plan = currentPlan(), d = district(), p = scopeP(), act = U.actionFor(p), a = HG.plan.assumptions, P = params();
    const total = U.canalNumbers(plan.funded, P), piped = plan.funded.filter((c) => c.piped).length;
    $("budgetOut").textContent = U.usd(state.budget);
    const perAf = (x) => (x > 0 ? "$" + U.num(plan.spent / x, 2) : "n/a");
    let rows;
    if (d) {
      rows = "<h3>Canals in sealing order</h3><div class=\"scroll\"><table class=\"t\"><tr><th>#</th><th>Canal</th><th class=\"r\">km</th><th class=\"r\">Costs</th><th class=\"r\">Takes</th><th class=\"r\">Saves</th></tr>" +
        plan.ordered.slice(0, 250).map((c, i) => { const n = U.canalNumbers([c], P), on = plan.fundedIds.has(c.id); return '<tr class="click ' + (on ? "" : "off") + '" data-act="canal" data-id="' + c.id + '"><td>' + (i + 1) + "</td><td>" + (on ? "<b>" + U.esc(c.name) + "</b>" : U.esc(c.name)) + (c.piped ? '<span class="flag">piped?</span>' : "") + '<br><span class="small muted">' + U.esc(c.soil) + '</span></td><td class="r">' + U.num(c.km, 2) + '</td><td class="r cost">' + U.usd(n.usd) + '</td><td class="r time">' + U.workTime(n.crewDays) + '</td><td class="r save">' + afMid(n) + " af</td></tr>"; }).join("") +
        "</table></div><p class=\"credit\">Bold rows are funded. Time is for one crew; saving is the middle of the range, in acre-feet. Click a row to find the canal on the map." + (plan.ordered.length > 250 ? " Showing the first 250 of " + plan.ordered.length + "; the download has every funded canal." : "") + "</p>";
    } else {
      const by = {};
      plan.funded.forEach((c) => { (by[c.district] = by[c.district] || []).push(c); });
      const order = Object.keys(by).map((i) => ({ i, n: U.canalNumbers(by[i], P), count: by[i].length })).sort((x, y) => y.n.usd - x.n.usd);
      rows = "<h3>Where the money goes</h3><div class=\"scroll\"><table class=\"t\"><tr><th>District</th><th class=\"r\">Canals</th><th class=\"r\">Costs</th><th class=\"r\">Takes</th><th class=\"r\">Saves</th></tr>" +
        order.map((r) => '<tr class="click" data-act="district" data-i="' + r.i + '"><td><b>' + U.esc(HG.districts[r.i].name) + "</b><div class=\"gauge\" style=\"height:5px;margin:5px 0 0\"><i style=\"background:var(--blue);width:" + (100 * r.n.usd / order[0].n.usd) + '%"></i></div></td><td class="r">' + r.count + '<br><span class="small muted">' + U.num(r.n.km, 1) + ' km</span></td><td class="r cost">' + U.usd(r.n.usd) + '</td><td class="r time">' + U.workTime(r.n.crewDays) + '</td><td class="r save">' + afMid(r.n) + " af</td></tr>").join("") +
        "</table></div><p class=\"credit\">" + order.length + " of " + HG.districts.length + " districts receive money. Time is for one crew in each district. Click a district to open its own canal list.</p>";
    }
    $("budgetResult").innerHTML =
      triple(total) +
      '<div class="card action ' + act.key + '"><span class="small muted">At a ' + U.pct(p) + " chance of a drought season" + (state.severity != null ? " (your what-if)" : " (the forecast)") + "</span><b>" + act.title + "</b>" + act.text + "</div>" +
      '<div class="kpis">' +
        kpi("Canals to seal", plan.funded.length + " segments", U.num(plan.km, 1) + " km, in the order below") +
        kpi("Sealant cost per acre-foot kept", perAf(total.afHigh) + " to " + perAf(total.afLow), "materials only; an acre-foot is worth about $" + U.num(U.USD_PER_AF) + " to farms in a shortage") +
      "</div>" +
      (piped ? '<p class="note">' + piped + " of the funded segments are mapped as piped or culverted in OpenStreetMap. Check those on the ground first: sealing a pipe saves nothing.</p>" : "") + rows +
      "<h3>How to carry it out</h3><div class=\"card\"><ol class=\"todo\">" +
        "<li><b>Walk the " + plan.funded.length + " funded canal segments (" + U.num(plan.km, 1) + " km).</b> Confirm each is unlined, open and carries water. Strike any that are lined or piped: no public data says for certain which are.</li>" +
        "<li><b>Order sealant for about " + U.num(plan.sqft) + " square feet</b> of wetted canal (" + a.wetted_width_ft + " ft assumed width). Materials: " + U.usd(plan.spent) + ". Labour and equipment are extra and not priced here.</li>" +
        "<li><b>Schedule " + P.crews + (P.crews === 1 ? " crew" : " crews") + " for about " + U.workTime(total.days) + " of work,</b> finishing before the first irrigation, ideally by early March. Start from the top of the list.</li>" +
        "<li><b>Measure, then repeat.</b> One application lasts about " + a.days_one_application_lasts + " days. Measure flow in and out of a sealed stretch to see what was really saved before paying for a second round.</li>" +
      "</ol></div>" +
      '<div class="rowBtns"><button class="btn" data-act="go" data-step="sim">Simulate this plan &rarr;</button><button class="btn ghost" data-act="csv">Download the canal list (CSV)</button></div>' +
      '<p class="note" style="margin-top:16px">Estimate from published figures, not a prediction and not a tested result. The time is our own assumption about crew speed. ' + U.esc(HG.plan.note) + "</p>";
    syncMap();
  }
  function downloadCsv() {
    const plan = currentPlan(), P = params();
    const lines = [["order", "canal", "kind", "mapped_as_piped", "district", "county_fips", "soil", "seepage_gal_sqft_day", "km", "sealant_usd", "one_crew_days", "saved_acre_feet_low", "saved_acre_feet_high"].join(",")];
    plan.funded.forEach((c, i) => { const n = U.canalNumbers([c], P); lines.push([i + 1, '"' + c.name.replace(/"/g, '""') + '"', '"' + (c.kind || "") + '"', c.piped ? "yes" : "no", '"' + (c.district >= 0 ? HG.districts[c.district].name : "") + '"', c.fips, '"' + c.soil + '"', c.rate, c.km, n.usd.toFixed(2), n.crewDays.toFixed(2), n.afLow.toFixed(2), n.afHigh.toFixed(2)].join(",")); });
    const link = U.el("a", { href: URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" })), download: "canal-sealing-plan.csv" });
    document.body.appendChild(link); link.click(); link.remove();
  }

  /* ---------- Step 3: Simulation ---------- */
  const POLICIES = [
    { trigger: "never", name: "Do nothing", css: "", blurb: "No canal work. Losses are paid for afterwards." },
    { trigger: "declared", name: "Wait for the declaration", css: "react", blurb: "Seal only after 8 straight weeks of severe drought, plus paperwork." },
    { trigger: "forecast", name: "Act on the forecast", css: "act", blurb: "Seal before the season whenever the forecast warns." },
  ];
  const SLIDERS = [   // the assumptions the user can move: [parameter, min, max, step, how to show it]
    ["cut", 0.28, 0.87, 0.01, (v) => Math.round(v * 100) + "%"],
    ["widthFt", 10, 40, 1, (v) => v + " ft"],
    ["fullAt", 30, 80, 1, (v) => v + "%"],
    ["zeroAt", 0, 29, 1, (v) => v + "%"],
    ["paperworkWeeks", 0, 26, 1, (v) => v + " weeks"],
    ["reliefShare", 0, 1, 0.05, (v) => Math.round(v * 100) + "%"],
    ["crews", 1, 10, 1, (v) => v],
    ["kmPerCrewDay", 1, 20, 1, (v) => v + " km"],
  ];

  /* What the engine needs for the current scope: its weekly record, its canals and the money at stake. */
  function simScope() {
    const d = district();
    const system = d && usesElephantButte(d) ? "Elephant Butte" : "Amistad-Falcon";
    const members = d ? [d] : HG.districts.filter((x) => !usesElephantButte(x));
    const fips = Array.from(new Set([].concat.apply([], members.map((x) => x.fips))));
    const ids = new Set(members.map((x) => HG.districts.indexOf(x)));
    const canals = U.canals.filter((c) => ids.has(c.district) && c.rank != null);
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
    return { weeks, canals: canals.slice().sort((a, b) => a.rank - b.rank), canalsUnranked: canals,
             demandAf: U.PUBLISHED.valleyIrrigationAf * share, revenueAtStake: U.PUBLISHED.worstCaseRevenue * share,
             share, system, pNow, outsideValley: members.some((x) => !x.fips.some((f) => SIM.valley.indexOf(f) >= 0)), members: members.length };
  }
  /* The frozen model's hit rates on 2020 to 2025, used to decide how often a simulated warning is right. */
  function hitRates() {
    const t = FROZEN ? FROZEN.test.preSeason.forecast : { recall: HG.trigger.rules[0].recall, falseAlarms: HG.trigger.rules[0].false_alarms, rows: HG.trigger.rows, droughtSeasons: HG.trigger.drought_seasons };
    return { recall: t.recall, falseAlarm: t.falseAlarms / Math.max(1, t.rows - t.droughtSeasons) };
  }

  function renderSim() {
    const d = district(), p = params();
    $("view").innerHTML =
      (d ? '<button class="back" data-act="state">&larr; All of Texas</button>' : "") +
      "<h2>Simulation: do nothing, or act</h2><div class=\"sub\">" + U.esc(scopeName()) + ". Every future gets the same weather, the same reservoirs and the same prices. Only the decision differs.</div>" +
      '<div class="card"><div class="seg" id="simMode"><button data-m="today" class="' + (state.simMode === "today" ? "on" : "") + '">From today, 5 years forward</button><button data-m="check" class="' + (state.simMode === "check" ? "on" : "") + '">Check it on 2020 to 2025</button></div>' +
      '<div class="field"><label for="simBudget">Sealing budget in a year you act <output id="simBudgetOut"></output></label><input id="simBudget" type="range" min="0" max="' + maxBudget() + '" step="' + budgetStep() + '" value="' + state.budget + '"></div></div>' +
      '<div id="simResult"></div>' +
      '<details class="assume"><summary>Assumptions you can change (' + SLIDERS.length + ")</summary>" +
      SLIDERS.map(([k, min, max, step, show]) => '<div class="field"><label for="a_' + k + '"><span>' + E.DEFAULTS[k].label + ' <span class="tag ' + E.DEFAULTS[k].tag + '">' + E.DEFAULTS[k].tag + '</span></span><output id="o_' + k + '">' + show(p[k]) + '</output></label><input type="range" data-param="' + k + '" id="a_' + k + '" min="' + min + '" max="' + max + '" step="' + step + '" value="' + p[k] + '"></div>').join("") +
      '<button class="btn small ghost" data-act="resetAssume">Reset to defaults</button></details>' +
      '<div id="simNotes"></div>';
    renderSimResult();
  }

  /* A line chart as SVG. series = [{ name, color, values, dash }], labels = x-axis labels. band = optional { low, high }. */
  function lineChart(series, labels, fmt, band) {
    const W = 640, H = 230, L = 62, R = 12, T = 12, B = 26;
    const every = series.reduce((a, s) => a.concat(s.values), band ? band.low.concat(band.high) : []);
    const max = Math.max(0, Math.max.apply(null, every)), min = Math.min(0, Math.min.apply(null, every)), span = (max - min) || 1;
    const x = (i) => L + (W - L - R) * i / Math.max(1, labels.length - 1), y = (v) => T + (H - T - B) * (1 - (v - min) / span);
    let out = '<svg viewBox="0 0 ' + W + " " + H + '">';
    for (let g = 0; g <= 4; g++) { const v = min + span * g / 4; out += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y(v) + '" y2="' + y(v) + '"/><text x="' + (L - 6) + '" y="' + (y(v) + 4) + '" text-anchor="end">' + fmt(v) + "</text>"; }
    let lastLabel = null;
    labels.forEach((lab, i) => { if (lab !== lastLabel && (labels.length < 30 || i % Math.ceil(labels.length / 7) === 0)) { out += '<text x="' + x(i) + '" y="' + (H - 6) + '" text-anchor="middle">' + lab + "</text>"; lastLabel = lab; } });
    if (band) out += '<polygon fill="' + band.color + '" opacity=".18" points="' + band.high.map((v, i) => x(i) + "," + y(v)).join(" ") + " " + band.low.map((v, i) => x(i) + "," + y(v)).reverse().join(" ") + '"/>';
    series.forEach((s) => { out += '<polyline fill="none" stroke="' + s.color + '" stroke-width="2.4" stroke-linejoin="round"' + (s.dash ? ' stroke-dasharray="5 4"' : "") + ' points="' + s.values.map((v, i) => x(i) + "," + y(v)).join(" ") + '"/>'; });
    return out + "</svg>" + '<div class="legend" style="margin-top:6px">' + series.map((s) => '<span><i class="lineKey" style="background:' + s.color + '"></i>' + s.name + "</span>").join("") + "</div>";
  }

  /* Hand the two futures (do nothing, act on the forecast) to The Fork, week by week. */
  let forkWeeks = [];
  function loadFork(nothing, act, system) {
    const flat = (run) => [].concat.apply([], run.years.map((y) => y.weekly.map((w, i) => Object.assign({}, w, { relief: i === y.weekly.length - 1 ? y.relief : 0 }))));
    const a = flat(nothing), b = flat(act);
    let sums = { l: { spend: 0, loss: 0, relief: 0 }, r: { spend: 0, loss: 0, relief: 0 } };
    forkWeeks = a.map((w, i) => {
      const add = (s, x) => { s.spend += x.spend; s.loss += x.loss; s.relief += x.relief; return Object.assign({}, s); };
      return { date: w.date, pct: w.pct == null ? 0 : w.pct, demand: w.demand, left: w, right: b[i], sumL: add(sums.l, w), sumR: add(sums.r, b[i]) };
    });
    $("forkSeek").max = forkWeeks.length - 1;
    const reliefMax = Math.max.apply(null, a.map((w) => w.relief).concat([1]));
    fork.load({ weeks: forkWeeks, system, leftName: "Do nothing", rightName: "Act on the forecast", reliefUnit: reliefMax / 20 });
  }
  const fork = window.HGFork.create({ canvas: $("fork"), stage: $("stage"), onTick(i, playing) {
    const w = forkWeeks[i]; if (!w) return;
    $("forkSeek").value = i; $("forkPlay").textContent = playing ? "Pause" : (i >= forkWeeks.length - 1 ? "Replay" : "Play");
    $("forkDate").textContent = "Week of " + U.niceDate(w.date);
    const row = (label, l, r) => "<tr><td>" + label + "</td><td>" + money(l) + "</td><td>" + money(r) + "</td></tr>";
    const totalL = w.sumL.spend + w.sumL.loss, totalR = w.sumR.spend + w.sumR.loss;
    $("forkLedger").innerHTML = "<h4>Running ledger</h4><table><tr class=\"h\"><td></td><td>Nothing</td><td>Act</td></tr>" +
      row("Sealing", w.sumL.spend, w.sumR.spend) + row("Crops lost", w.sumL.loss, w.sumR.loss) + row("Relief paid", w.sumL.relief, w.sumR.relief) +
      '<tr class="sum"><td>Total cost</td><td>' + money(totalL) + "</td><td>" + money(totalR) + "</td></tr>" +
      '<tr><td colspan="3" style="text-align:center;color:' + (totalL - totalR >= 0 ? "var(--low)" : "var(--warning)") + ';font-weight:700;padding-top:4px">' + (totalL - totalR >= 0 ? "Acting is " + money(totalL - totalR) + " ahead" : "Acting is " + money(totalR - totalL) + " behind") + "</td></tr></table>";
  } });
  $("forkPlay").onclick = () => (fork.playing() ? fork.pause() : fork.play());
  $("forkSeek").oninput = (e) => { fork.pause(); fork.seek(Number(e.target.value)); };
  function forkTop() {
    $("forkTop").innerHTML = state.simMode !== "today" ? "<span>The real record, 2020 to 2025: years the forecast model never saw.</span>" :
      "<span>Hit both futures with:</span>" + SHOCKS.map((s) => '<button class="sbtn ' + (state.shocks[s.key] ? "on" : "") + '" data-shock="' + s.key + '" title="' + s.note + ' (our assumption)">' + s.label + "</button>").join("");
  }
  $("forkTop").addEventListener("click", (e) => { const b = e.target.closest("[data-shock]"); if (b) { state.shocks[b.dataset.shock] = !state.shocks[b.dataset.shock]; renderSimResult(); fork.play(); } });

  function renderSimResult() {
    const scope = simScope(), over = Object.assign({}, state.overrides, { budget: state.budget }), P = E.makeParams(over);
    $("simBudgetOut").textContent = U.usd(state.budget);
    const plan = E.fundCanals(scope.canals, state.budget, P), planN = U.canalNumbers(plan.funded, P);
    const li = (cls, text, tag) => '<li class="' + cls + '">' + text + (tag ? ' <span class="tag ' + tag + '">' + tag + "</span>" : "") + "</li>";
    const who = scope.members > 1 ? scope.members + " districts on the " + scope.system + " system" : "this district";
    let html = "<h3>What acting means each year you act</h3>" + triple(planN);

    if (state.simMode === "today") {
      const res = reservoirFor(district()), hit = hitRates();
      const on = SHOCKS.filter((s) => state.shocks[s.key]);
      const run = E.fromToday(scope, POLICIES.map((pol) => ({ trigger: pol.trigger })), over, {
        startDate: TODAY, pctNow: res.pct == null ? 50 : res.pct, pNow: scope.pNow, years: 5, draws: 300, seed: 11,
        cutoffYear: 2020, recall: hit.recall, falseAlarm: hit.falseAlarm,
        shocks: on.filter((s) => s.shock).map((s) => s.shock), secondDryYear: on.some((s) => s.secondDryYear) });
      const base = run.policies[0].draws, endYear = Number(TODAY.slice(0, 4)) + 5;
      html = '<div class="card small"><b>Starts today, ' + U.niceDate(TODAY) + ".</b> " + scope.system + " reservoirs at " + (res.pct == null ? "n/a" : res.pct + "%") + " (" + (res.live ? "live reading" : "saved reading") + " of " + U.niceDate(res.date) + "). " +
        "Chance of a drought season in the next 6 months: <b>" + U.pct(scope.pNow) + "</b>, from a model that " + (FROZEN ? "stopped learning on " + U.niceDate(FROZEN.trainedOn.to) + " and is reading the Drought Monitor week of " + U.niceDate(FROZEN.liveWeek) : "was tested on later years") + ". " +
        "Futures are built from " + run.libraryYears.length + " real years, " + run.libraryYears[0] + " to " + run.libraryYears[run.libraryYears.length - 1] + " (" + run.dryYears.length + " of them had a drought season). Nothing from 2020 on is used to build them." +
        (on.length ? " <b>Added: " + on.map((s) => s.label.toLowerCase() + " (" + s.note + ")").join("; ") + ".</b>" : "") + "</div>" + html +
        "<h3>Total cost to " + endYear + ": crops lost plus sealing</h3><div class=\"futures\">" + POLICIES.map((pol, i) => {
          const s = run.policies[i].summary.cost;
          const gains = run.policies[i].draws.map((t, k) => base[k].cost - t.cost).sort((a, b) => a - b);
          const mid = gains[Math.floor(gains.length / 2)], worse = gains.filter((g) => g < 0).length;
          return '<div class="future ' + pol.css + '"><span>' + pol.name + "</span><b>" + money(s.mid) + "</b><small>" + money(s.low) + " to " + money(s.high) + " in 8 of 10 futures</small>" +
            (i ? '<em class="' + (mid >= 0 ? "" : "bad") + '">' + (mid >= 0 ? money(mid) + " better" : money(-mid) + " worse") + " than doing nothing</em><small>worse off in " + worse + " of " + gains.length + " futures</small>" : "<small>" + pol.blurb + "</small>") + "</div>";
        }).join("") + "</div>" +
        '<p class="credit" style="margin:8px 0 0">300 possible futures for ' + who + ". The big number is the middle one. The picture on the left plays the middle future, week by week.</p>" +
        "<h3>Reservoir storage in those futures</h3><div class=\"chart\">" +
        lineChart([{ name: "Middle future", color: U.TIER_COLOR.Low, values: run.fan.map((w) => w.mid) },
                   { name: "Farms get all their water above this", color: U.LEVEL_COLOR["Unknown soil"], values: run.fan.map(() => P.fullAt), dash: true },
                   { name: "Farms get none below this", color: U.TIER_COLOR.Warning, values: run.fan.map(() => P.zeroAt), dash: true }],
                  run.fan.map((w) => w.date.slice(0, 4)), (v) => Math.round(v) + "%", { low: run.fan.map((w) => w.low), high: run.fan.map((w) => w.high), color: U.TIER_COLOR.Low }) +
        '<p class="credit" style="margin:6px 0 0">The band holds 8 of 10 futures. Storage starts at today\'s reading and then rises and falls the way it did in the real years drawn.</p></div>';
      const act = run.policies[2], wait = run.policies[1];
      html += "<h3>The receipt</h3><ul class=\"receipt\">" +
        li(base.length && act.summary.cost.mid <= run.policies[0].summary.cost.mid ? "for" : "against", "<b>Middle future: acting costs " + money(act.summary.cost.mid) + ", doing nothing costs " + money(run.policies[0].summary.cost.mid) + ".</b> Sealing spend in the middle future: " + money(act.summary.spend.mid) + " over five years.", "assumption") +
        li(act.summary.cost.mid <= wait.summary.cost.mid ? "for" : "against", "<b>Against waiting for a declaration:</b> waiting ends at " + money(wait.summary.cost.mid) + " in the middle future. A declaration needs 8 straight weeks of severe drought and then paperwork, so the sealant often goes on late in the season.", "assumption") +
        li("against", "<b>The forecast is wrong sometimes.</b> In these futures it warns before " + Math.round(hit.recall * 100) + "% of dry seasons and also before " + Math.round(hit.falseAlarm * 100) + "% of wet ones. Each wrong warning costs a full round of sealing: " + U.usd(plan.spent) + ".", "pipeline") +
        li("", "<b>Saved water only counts in a shortage.</b> When the reservoirs are over " + P.fullAt + "% farms get all their water and sealing earns nothing that year.", "assumption") +
        "</ul>";
      loadFork(run.sample[0], run.sample[2], scope.system);
    } else {
      // Check: the real 2020 to 2025 record, with the forecasts the frozen model made for those years.
      const test = Object.assign({}, scope, { weeks: scope.weeks.filter((w) => w.year >= 2020 && w.year <= 2025) });
      const runs = POLICIES.map((pol) => E.simulate(test, { trigger: pol.trigger }, over));
      const d1 = E.simulate(test, { trigger: "d1" }, over), always = E.simulate(test, { trigger: "always" }, over);
      const [nothing, react, act] = runs, years = nothing.years.map((y) => y.year);
      const diff = (a, b) => a.totals.cost - b.totals.cost;
      const better = (v, other) => (Math.abs(v) < 0.002 * act.totals.cost ? "ended level with " + other : v > 0 ? "ended " + money(v) + " ahead of " + other : "ended " + money(-v) + " behind " + other);
      const t = FROZEN && FROZEN.test.preSeason;
      html = '<div class="card small"><b>A test, not a forecast.</b> The model stopped learning ' + (FROZEN ? "on " + U.niceDate(FROZEN.trainedOn.to) : "before 2020") + ". Here it is run on the six years after that, which it never saw, with the real drought record and the real reservoir levels.</div>" + html +
        "<h3>Total cost, 2020 to 2025: crops lost plus sealing</h3><div class=\"futures\">" + POLICIES.map((pol, i) => {
          const tt = runs[i].totals, saved = nothing.totals.cost - tt.cost;
          return '<div class="future ' + pol.css + '"><span>' + pol.name + "</span><b>" + money(tt.cost) + "</b><small>crops " + money(tt.loss) + " + sealing " + money(tt.spend) + "</small>" +
            (i ? '<em class="' + (saved >= 0 ? "" : "bad") + '">' + (saved >= 0 ? money(saved) + " better" : money(-saved) + " worse") + " than doing nothing</em>" : "<small>" + pol.blurb + "</small>") + "</div>";
        }).join("") + "</div>" +
        '<p class="credit" style="margin:8px 0 0">For ' + who + ". Lost crops are counted at net revenue per acre-foot of missing irrigation water.</p>" +
        "<h3>Running gain over doing nothing</h3><div class=\"chart\">" +
        lineChart(POLICIES.slice(1).map((pol, i) => { let sum = 0; return { name: pol.name, color: i ? U.LEVEL_COLOR.Low : U.TIER_COLOR.Watch, values: runs[i + 1].years.map((y, k) => (sum += nothing.years[k].loss - y.loss - y.spend)) }; }), years, money) +
        '<p class="credit" style="margin:6px 0 0">Crop loss avoided minus sealing cost. Flat in wet years: saved water only counts when there is a shortage to fill.</p></div>' +
        (t ? "<h3>How the frozen model did on those years</h3><div class=\"scroll\" style=\"max-height:none\"><table class=\"t\"><tr><th>January to March warnings</th><th class=\"r\">Drought seasons caught</th><th class=\"r\">Warnings that were right</th></tr>" +
          "<tr><td><b>Our forecast</b> (trained before 2020)</td><td class=\"r\">" + t.forecast.caught + " of " + t.forecast.droughtSeasons + " (" + Math.round(t.forecast.recall * 100) + "%)</td><td class=\"r\">" + Math.round(t.forecast.precision * 100) + "%</td></tr>" +
          "<tr><td>Simple rule: already in moderate drought</td><td class=\"r\">" + t.d1Rule.caught + " of " + t.d1Rule.droughtSeasons + " (" + Math.round(t.d1Rule.recall * 100) + "%)</td><td class=\"r\">" + Math.round(t.d1Rule.precision * 100) + "%</td></tr></table></div>" +
          '<p class="credit">County-months in the 14 Texas river counties, ' + U.niceDate(FROZEN.test.from) + " to " + U.niceDate(FROZEN.test.to) + ". The forecast and the simple rule are close. We show both.</p>" : "") +
        "<h3>The receipt</h3><ul class=\"receipt\">" +
        li(diff(nothing, act) >= 0 ? "for" : "against", "<b>Acting on the forecast " + better(diff(nothing, act), "doing nothing") + ".</b> It sealed in " + act.totals.yearsActed + " of " + years.length + " years.", "assumption") +
        li(diff(react, act) > 0 ? "for" : "against", "<b>Acting on the forecast " + better(diff(react, act), "waiting for a declaration") + ".</b> Waiting sealed in " + react.totals.yearsActed + " years.", "assumption") +
        li(diff(d1, act) > 0 ? "for" : "against", "<b>The forecast " + better(diff(d1, act), "the simple rule \"seal if already in moderate drought\"") + ".</b>", "pipeline") +
        li(diff(always, act) > 0 ? "for" : "against", "<b>The forecast " + better(diff(always, act), "sealing every single year") + ".</b> Sealant is cheap next to lost crops, so sealing every year is hard to beat.", "assumption") +
        li("against", "<b>False alarms: " + act.totals.falseAlarms + " of " + act.totals.yearsActed + " years acted.</b> In those years sealing was paid for and there was no shortage for the saved water to fill.", "pipeline") +
        "</ul>";
      loadFork(nothing, act, scope.system);
    }
    $("simResult").innerHTML = html;
    forkTop();

    $("simNotes").innerHTML =
      (scope.outsideValley ? '<p class="note">The published farm-loss figure covers only Cameron, Hidalgo, Starr and Willacy counties. Applying its value per acre-foot here is our extrapolation.</p>' : "") +
      (!district() ? '<p class="small muted">The state run covers the districts on the Amistad-Falcon system. El Paso and Hudspeth districts draw on Elephant Butte; open one of them to simulate it.</p>' : "") +
      "<h3>What the money figures rest on</h3><div class=\"card small\">" +
      '<p><span class="tag published">published</span> A year with no irrigation water costs the Valley ' + U.usd(U.PUBLISHED.worstCaseRevenue) + ' in net crop revenue and 8,404 jobs (<a target="_blank" rel="noopener" href="' + U.PUBLISHED.worstCaseUrl + '">Texas A&amp;M AgriLife, 2023</a>). Full irrigation demand is 1,349,369 acre-feet a year (<a target="_blank" rel="noopener" href="' + U.PUBLISHED.valleyIrrigationUrl + '">Region M Water Plan, Table 2-8</a>, 2011 use). Dividing the two gives about $367 per acre-foot; that division is ours.</p>' +
      '<p><span class="tag assumption">assumption</span> This scope holds ' + Math.round(scope.share * 100) + "% of the Valley districts' canal length, so it is given that share of the water and of the revenue: " + U.usd(scope.revenueAtStake) + " a year at stake.</p>" +
      '<p><span class="tag assumption">assumption</span> How much water farms get is read off reservoir storage with a straight line between two of the sliders above. The real rule is an accounting of reserves (<a target="_blank" rel="noopener" href="' + U.PUBLISHED.allocationRule.url + '">' + U.PUBLISHED.allocationRule.text + "</a>): cities are served first and irrigation gets what is left.</p>" +
      '<p><span class="tag pipeline">pipeline</span> Drought classes and reservoir levels are the real weekly records. "Declaration" uses the federal fast-track rule: 8 straight weeks at D2 (<a target="_blank" rel="noopener" href="' + U.PUBLISHED.disasterRule.url + '">' + U.PUBLISHED.disasterRule.text + "</a>).</p>" +
      '<p style="margin:0"><span class="tag assumption">assumption</span> Sealing is one application of sealant on unlined canals, materials only, and it has not been field-tested on the Rio Grande. Crew speed is our own guess. Permanent lining is a different job: one 3,900-foot main-canal project was budgeted at $5.1 million (<a target="_blank" rel="noopener" href="' + U.PUBLISHED.liningExample.url + '">' + U.PUBLISHED.liningExample.text + "</a>).</p></div>";
  }

  /* ---------- Putting it together ---------- */
  function refresh(refit) {
    document.querySelectorAll("#stepper button").forEach((b) => b.classList.toggle("on", b.dataset.step === state.step));
    $("stage").classList.toggle("sim", state.step === "sim");
    $("scopeBtn").innerHTML = "<small>" + (district() ? "District" : "View") + "</small>" + U.esc(scopeName()) + " &#9662;";
    $("viewScope").textContent = district() ? "My district" : "All of Texas";
    ({ risk: renderRisk, budget: renderBudget, sim: renderSim })[state.step]();
    syncMap();
    $("view").scrollTop = 0;
    if (state.step === "sim") fork.play(); else fork.pause();
    if (refit && !map.isScanning()) map.fitScope();
  }
  function setScope(scope, noScan) {
    state.scope = scope; state.county = null; state.canal = null; state.severity = null;
    state.budget = defaultBudget();
    try { localStorage.setItem("hg-scope", scope === STATE ? "state" : HG.districts[scope].name); } catch (e) { /* storage can be blocked */ }
    history.replaceState(null, "", location.pathname + location.search + (scope === STATE ? "#state" : "#d=" + encodeURIComponent(HG.districts[scope].name)));
    $("onboard").classList.remove("open");
    let seen = false;
    try { seen = sessionStorage.getItem("hg-scanned") === "1"; sessionStorage.setItem("hg-scanned", "1"); } catch (e) { /* storage can be blocked */ }
    const scan = !noScan && !seen && state.step !== "sim" && location.search.indexOf("noscan") < 0;
    refresh(!scan);
    if (scan) map.runScan();                                 // the first visit of a session opens with the scan
  }

  /* Clicks inside the panel: every button carries data-act. */
  $("view").addEventListener("click", (e) => {
    const img = e.target.closest(".photos img");
    if (img) { $("lightbox").querySelector("img").src = img.src; $("lightbox").querySelector("p").textContent = img.alt; $("lightbox").classList.add("on"); return; }
    const t = e.target.closest("[data-act]");
    if (!t) return;
    const act = t.dataset.act;
    if (act === "go") { state.step = t.dataset.step; refresh(false); }
    if (act === "state") setScope(STATE, true);
    if (act === "district") setScope(Number(t.dataset.i), true);
    if (act === "closeCounty") { state.county = null; refresh(false); }
    if (act === "closeCanal") { state.canal = null; refresh(false); }
    if (act === "csv") downloadCsv();
    if (act === "resetAssume") { state.overrides = {}; renderSim(); }
    if (act === "canal") { state.canal = Number(t.dataset.id); map.flyToCanal(state.canal); refresh(false); }
  });
  $("lightbox").onclick = () => $("lightbox").classList.remove("on");
  $("view").addEventListener("click", (e) => {
    const sev = e.target.closest("#sev button"), mode = e.target.closest("#simMode button");
    if (sev) { state.severity = sev.dataset.p === "" ? null : Number(sev.dataset.p); renderBudget(); }
    if (mode) { state.simMode = mode.dataset.m; renderSim(); fork.play(); }
  });
  $("view").addEventListener("input", (e) => {
    if (e.target.id === "budget") { state.budget = Number(e.target.value); renderBudgetResult(); }
    if (e.target.id === "simBudget") { state.budget = Number(e.target.value); renderSimResult(); }
    if (e.target.dataset.param) {
      const k = e.target.dataset.param, row = SLIDERS.find((s) => s[0] === k);
      state.overrides[k] = Number(e.target.value);
      if (k === "fullAt" || k === "zeroAt") {                   // keep "none" below "all"
        const p = params();
        if (p.zeroAt >= p.fullAt) state.overrides.zeroAt = p.fullAt - 1;
      }
      $("o_" + k).textContent = row[4](state.overrides[k]);
      if (state.step === "sim") renderSimResult(); else renderBudgetResult();
    }
  });
  $("stepper").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (b) { state.step = b.dataset.step; refresh(false); }
  });
  $("themeBtn").onclick = () => {
    U.setTheme(U.theme() === "dark" ? "light" : "dark");
    $("themeBtn").textContent = U.theme() === "dark" ? "Light mode" : "Dark mode";
    map.readTheme(); fork.readTheme(); refresh(false);
  };
  $("themeBtn").textContent = U.theme() === "dark" ? "Light mode" : "Dark mode";

  /* ---------- The chooser ---------- */
  function fillPick(query) {
    const q = (query || "").toLowerCase();
    $("pickList").innerHTML = HG.districts.map((d, i) => ({ d, i }))
      .filter(({ d }) => !q || d.name.toLowerCase().indexOf(q) >= 0 || d.counties.join(" ").toLowerCase().indexOf(q) >= 0)
      .map(({ d, i }) => '<button data-i="' + i + '"><span><b>' + U.esc(d.name) + "</b><small>" + d.counties.join(", ") + " · " + U.num(d.canalKm) + " km of canals</small></span>" + chip(d.risk) + "</button>").join("") ||
      '<p style="color:#c9d8e8">No district matches. The portal covers the ' + HG.districts.length + " Texas districts on the Rio Grande.</p>";
  }
  function openChooser() { $("pick").classList.remove("open"); $("onboard").classList.add("open"); }
  $("roleState").addEventListener("click", () => setScope(STATE));
  $("roleDistrict").addEventListener("click", () => { fillPick(""); $("pick").classList.add("open"); $("pickSearch").focus(); $("pick").scrollIntoView({ behavior: "smooth" }); });
  $("pickSearch").addEventListener("input", (e) => fillPick(e.target.value));
  $("pickList").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) setScope(Number(b.dataset.i)); });
  $("scopeBtn").addEventListener("click", openChooser);

  /* ---------- Live readings ---------- */
  // api/live fetches today's reservoir storage (the public source does not allow browsers to
  // read it directly). If it cannot be reached, the page keeps the reading saved by the last
  // pipeline refresh and says so.
  function showLive() {
    const live = state.live && state.live.systems;
    $("live").classList.toggle("saved", !live);
    $("liveText").textContent = (live ? "Reservoirs live · " : "Reservoirs saved · ") + "forecast week of " + U.niceDate(HG.week);
  }
  showLive();
  fetch("api/live").then((r) => (r.ok ? r.json() : Promise.reject())).then((data) => {
    if (data && data.systems) { state.live = data; showLive(); if (state.scope != null) { if (state.step === "risk") renderRisk(); if (state.step === "sim") renderSimResult(); syncMap(); } }
  }).catch(() => { /* keep the saved reading */ });

  /* ---------- Start: use the link, then the remembered choice, else ask ---------- */
  const byName = (name) => HG.districts.findIndex((d) => d.name === name);
  const hash = decodeURIComponent(location.hash.slice(1));
  let saved = null;
  try { saved = localStorage.getItem("hg-scope"); } catch (e) { /* storage can be blocked */ }
  if (location.search.indexOf("step=") >= 0) state.step = location.search.split("step=")[1].split("&")[0];   // for links straight to a step
  if (hash === "state") setScope(STATE);
  else if (hash.indexOf("d=") === 0 && byName(hash.slice(2)) >= 0) setScope(byName(hash.slice(2)));
  else if (saved === "state") setScope(STATE);
  else if (saved && byName(saved) >= 0) setScope(byName(saved));
  else { state.scope = STATE; state.budget = defaultBudget(); refresh(true); openChooser(); }
})();
