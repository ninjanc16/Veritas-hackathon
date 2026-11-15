/*
  platform.js: the platform (app.html).

  HOW IT IS ORGANISED
    state      one object holding every choice the user has made (scope, step, budget ...)
    the map    js/scanmap.js draws it; this file only tells it what to show
    the twin   js/twin.js draws the simulation (one district, twice); this file hands it the weeks
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

  const state = { scope: null, step: "risk", mapMode: "now", budget: null, severity: null, simStep: 2, simCase: "likely",
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
  /* A row of key figures: [[label, value, note], ...]. Plain rules between them, no boxes. */
  const stats = (rows) => '<dl class="stats">' + rows.map((r) => "<div><dt>" + r[0] + "</dt><dd>" + r[1] + "</dd>" + (r[2] ? "<small>" + r[2] + "</small>" : "") + "</div>").join("") + "</dl>";
  /* The three numbers every canal decision comes down to. n = U.canalNumbers(...). oneCrew = time for a single crew. */
  function triple(n, oneCrew, cls) {
    const p = params(), days = oneCrew ? n.crewDays : n.days;
    return '<dl class="stats three ' + (cls || "") + '">' +
      '<div class="cost"><dt>Cost</dt><dd>' + (n.usd >= 1e6 ? money(n.usd) : U.usd(n.usd)) + "</dd><small>sealant, " + U.num(n.km, n.km < 10 ? 2 : 1) + " km; labour extra</small></div>" +
      '<div class="time"><dt>Time</dt><dd>' + U.workTime(days) + "</dd><small>" + (oneCrew ? "1 crew" : p.crews + (p.crews === 1 ? " crew" : " crews")) + ", " + p.kmPerCrewDay + " km a day</small></div>" +
      '<div class="save"><dt>Water kept</dt><dd>' + (n.afHigh > 0 ? af(n) + " af" : "unknown") + "</dd><small>" + (n.afHigh > 0 ? "per 90-day application; " + money(n.worthLow) + " to " + money(n.worthHigh) + " in a shortage" : "no seepage rate for this soil") + "</small></div></dl>";
  }
  function gauge(p) {
    const tier = U.tierFor(p);
    return '<div class="gauge"><i style="width:' + Math.min(100, p * 100) + "%;background:" + U.TIER_COLOR[tier] + '"></i><u style="left:' + HG.threshold * 100 + '%"></u></div>';
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
    // Start with every treatable canal funded. The simulation shows each extra dollar of sealant
    // still returns far more than it costs, so the full network is the plan the numbers favour.
    return maxBudget();
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
  const more = (title, body) => (body ? '<details class="more"><summary>' + title + "</summary>" + body + "</details>" : "");
  function renderRisk() {
    const d = district(), list = scopeCanals(), res = reservoirFor(d);
    const resStat = [res.name + " storage", res.pct == null ? "n/a" : res.pct + "%", (res.live ? "live, " : "saved, ") + U.niceDate(res.date)];
    let html = "";
    if (state.canal != null) html += canalCard(U.canals[state.canal]);
    if (state.county && !d) html += countyCard(state.county, true);
    if (d) {
      const act = U.actionFor(d.pSeason);
      const worst = Math.max.apply(null, d.fips.map((f) => U.countyByFips[f].dm || 0));
      const treatable = list.filter((c) => c.rank != null), all = U.canalNumbers(treatable, params());
      const named = namedCanals(list);
      html += '<button class="back" data-act="state">&larr; All districts</button>' +
        "<h2>" + U.esc(d.name) + "</h2><div class=\"sub\">" + U.esc(d.kind) + " · " + d.counties.join(", ") + " · week of " + U.niceDate(HG.week) + "</div>" +
        stats([
          ["Drought season, next 6 months", U.pct(d.pSeason), d.risk + "; warning line " + U.pct(HG.threshold)],
          ["Drought now", worst ? "D" + (worst - 1) : "None", U.DM_TEXT[worst].replace(/^D\d /, "")],
          resStat,
          ["Canals", U.num(d.canalKm) + " km", U.num(list.length) + " segments, " + U.num(treatable.length) + " rankable"],
        ]) + gauge(d.pSeason) +
        '<p class="rec ' + act.key + '"><b>' + act.title + ".</b> " + act.text.split(". ").slice(1).join(". ") + "</p>" +
        "<h3>All rankable canals sealed, one application</h3>" + (treatable.length ? triple(all) : '<p class="fn">No canal here can be ranked: drains, or soil with no published seepage rate.</p>') +
        '<div class="rowBtns"><button class="btn" data-act="go" data-step="budget">Budget plan &rarr;</button><button class="btn ghost" data-act="go" data-step="sim">Simulation &rarr;</button></div>' +
        "<h3>Canal length by leak class</h3>" + mixBar(list, (c) => c.level, (k) => U.LEVEL_COLOR[k]) +
        "<h3>Canal length by soil</h3>" + mixBar(list, (c) => c.soil || "Not looked up", (k) => { const r = HG.seepage[k]; return r == null ? U.LEVEL_COLOR["Unknown soil"] : r >= 7.48 ? U.TIER_COLOR.Warning : r >= 2.9 ? U.TIER_COLOR.Watch : U.TIER_COLOR.Low; }) +
        (named.length ? "<h3>Named canals (" + named.length + ")</h3><div class=\"scroll\"><table class=\"t\"><tr><th>Canal</th><th class=\"r\">km</th><th class=\"r\">Cost</th><th class=\"r\">Time</th><th class=\"r\">Kept, af</th></tr>" +
          named.slice(0, 80).map((g) => '<tr class="click" data-act="canal" data-id="' + g.segs[0].id + '"><td>' + U.esc(g.name) + ' <span class="muted">(' + g.segs.length + ")</span></td><td class=\"r\">" + U.num(g.km, 1) + "</td>" +
            (g.n.km > 0 ? '<td class="r">' + U.usd(g.n.usd) + '</td><td class="r">' + U.workTime(g.n.crewDays) + '</td><td class="r">' + af(g.n) + "</td>" : '<td class="r muted" colspan="3">not rankable</td>') + "</tr>").join("") +
          '</table></div><p class="fn">One crew, one application. Segment count in brackets. Select a row to find it on the map.</p>' : "") +
        more("Open issues from live data", issuesFor(d)) +
        more("County profile and photos", d.fips.map((f) => countyCard(f, false)).join(""));
    } else {
      const inDrought = HG.texas.filter((c) => c.dm != null && c.dm >= 2).length;
      const warned = HG.river.filter((c) => c.pSeason >= HG.threshold).length;
      const dWarn = HG.districts.filter((x) => x.risk === "Warning").length;
      const all = U.canalNumbers(list.filter((c) => c.rank != null), params());
      html += "<h2>Texas, Rio Grande districts</h2><div class=\"sub\">" + HG.districts.length + " irrigation and water districts · 254 counties · week of " + U.niceDate(HG.week) + "</div>" +
        stats([
          ["Counties in drought (D1+)", inDrought + " / 254", "U.S. Drought Monitor"],
          ["River counties over warning line", warned + " / 14", "6-month forecast at " + U.pct(HG.threshold) + " or more"],
          resStat,
          ["Districts at Warning", dWarn + " / " + HG.districts.length, U.num(HG.plan.canal_km_in_districts) + " km of canal"],
        ]) +
        "<h3>All rankable canals sealed, one application</h3>" + triple(all) +
        '<div class="rowBtns"><button class="btn" data-act="go" data-step="budget">Budget plan &rarr;</button><button class="btn ghost" data-act="go" data-step="sim">Simulation &rarr;</button></div>' +
        "<h3>Districts by 6-month drought chance</h3><div class=\"scroll\" style=\"max-height:440px\"><table class=\"t\"><tr><th>District</th><th>Tier</th><th class=\"r\">Chance</th><th class=\"r\">Canal km</th></tr>" +
        HG.districts.map((x, i) => ({ x, i })).sort((a, b) => b.x.pSeason - a.x.pSeason).map(({ x, i }) =>
          '<tr class="click" data-act="district" data-i="' + i + '"><td>' + U.esc(x.name) + ' <span class="muted">' + x.counties.join(", ") + "</span></td><td>" + chip(x.risk) + '</td><td class="r">' + U.pct(x.pSeason) + '</td><td class="r">' + U.num(x.canalKm) + "</td></tr>").join("") +
        '</table></div><p class="fn">Select a district to open it. Select a county on the map for its profile.</p>' +
        more("Open issues from live data", issuesFor(null));
    }
    html += '<p class="fn">Forecast: random forest on the drought record, re-run weekly. In testing it matched, and did not clearly beat, the rule "already in moderate drought". Canals: USGS' + (HG.osm ? " plus " + U.num(HG.osm.added) + " from OpenStreetMap" : "") + ". No source records which canals are lined.</p>";
    $("view").innerHTML = html;
  }

  /* ---------- Step 2: Budget plan ---------- */
  function renderBudget() {
    const d = district(), all = costAll();
    $("view").innerHTML =
      (d ? '<button class="back" data-act="state">&larr; All districts</button>' : "") +
      "<h2>Budget plan</h2><div class=\"sub\">" + U.esc(scopeName()) + " · canals in sealing order for a given budget</div>" +
      (state.canal != null ? canalCard(U.canals[state.canal]) : "") +
      (all <= 0 ? '<p class="fn">No canal in this district can be ranked (drains, or soil with no published seepage rate).</p>' :
      '<div class="controls"><div class="field"><label for="budget">Sealing budget, one application <output id="budgetOut"></output></label>' +
      '<input id="budget" type="range" min="0" max="' + maxBudget() + '" step="' + budgetStep() + '" value="' + state.budget + '">' +
      '<div class="fn">Every rankable canal: ' + U.usd(all) + " in sealant.</div></div>" +
      '<div class="field"><label>Drought chance to plan for</label><div class="seg" id="sev">' +
      SEVERITIES.map((s) => '<button data-p="' + (s.p == null ? "" : s.p) + '" class="' + (state.severity === s.p ? "on" : "") + '">' + (s.p == null ? "Forecast (" + U.pct(scopeP0()) + ")" : s.label) + "</button>").join("") +
      "</div></div></div><div id=\"budgetResult\"></div>" +
      '<details class="more"><summary>Crew assumptions</summary>' + crewFields() + "</details>" +
      '<div id="budgetExtra"></div>');
    if (all > 0) renderBudgetResult();
  }
  function renderBudgetResult() {
    const plan = currentPlan(), d = district(), p = scopeP(), act = U.actionFor(p), a = HG.plan.assumptions, P = params();
    const total = U.canalNumbers(plan.funded, P), piped = plan.funded.filter((c) => c.piped).length;
    $("budgetOut").textContent = U.usd(state.budget);
    const perAf = (x) => (x > 0 ? "$" + U.num(plan.spent / x, 2) : "n/a");
    let rows;
    if (d) {
      rows = "<h3>Canals in sealing order</h3><div class=\"scroll\"><table class=\"t\"><tr><th>#</th><th>Canal</th><th class=\"r\">km</th><th class=\"r\">Cost</th><th class=\"r\">Time</th><th class=\"r\">Kept, af</th></tr>" +
        plan.ordered.slice(0, 250).map((c, i) => { const n = U.canalNumbers([c], P), on = plan.fundedIds.has(c.id); return '<tr class="click ' + (on ? "" : "off") + '" data-act="canal" data-id="' + c.id + '"><td>' + (i + 1) + "</td><td>" + U.esc(c.name) + (c.piped ? '<span class="flag">piped?</span>' : "") + ' <span class="muted">' + U.esc(c.soil) + '</span></td><td class="r">' + U.num(c.km, 2) + '</td><td class="r">' + U.usd(n.usd) + '</td><td class="r">' + U.workTime(n.crewDays) + '</td><td class="r">' + afMid(n) + "</td></tr>"; }).join("") +
        "</table></div><p class=\"fn\">Greyed rows are not funded. One crew; water kept is the middle of the tested range." + (plan.ordered.length > 250 ? " First 250 of " + plan.ordered.length + " shown; the CSV has every funded canal." : "") + "</p>";
    } else {
      const by = {};
      plan.funded.forEach((c) => { (by[c.district] = by[c.district] || []).push(c); });
      const order = Object.keys(by).map((i) => ({ i, n: U.canalNumbers(by[i], P), count: by[i].length })).sort((x, y) => y.n.usd - x.n.usd);
      rows = "<h3>Allocation by district</h3><div class=\"scroll\"><table class=\"t\"><tr><th>District</th><th class=\"r\">Segments</th><th class=\"r\">km</th><th class=\"r\">Cost</th><th class=\"r\">Time</th><th class=\"r\">Kept, af</th></tr>" +
        order.map((r) => '<tr class="click" data-act="district" data-i="' + r.i + '"><td>' + U.esc(HG.districts[r.i].name) + '</td><td class="r">' + r.count + '</td><td class="r">' + U.num(r.n.km, 1) + '</td><td class="r">' + U.usd(r.n.usd) + '</td><td class="r">' + U.workTime(r.n.crewDays) + '</td><td class="r">' + afMid(r.n) + "</td></tr>").join("") +
        "</table></div><p class=\"fn\">" + order.length + " of " + HG.districts.length + " districts funded. One crew per district. Select a district for its canal list.</p>";
    }
    $("budgetResult").innerHTML =
      triple(total) +
      stats([
        ["Segments funded", U.num(plan.funded.length), U.num(plan.km, 1) + " km"],
        ["Sealant per acre-foot kept", perAf(total.afHigh) + " to " + perAf(total.afLow), "an acre-foot is worth about $" + U.num(U.USD_PER_AF) + " in a shortage"],
      ]) +
      '<p class="rec ' + act.key + '"><b>' + act.title + ".</b> At a " + U.pct(p) + " chance of a drought season" + (state.severity != null ? " (your setting)." : " (the forecast).") + "</p>" +
      (piped ? '<p class="fn warn">' + piped + " funded segments are mapped as piped in OpenStreetMap. Check them first: a pipe does not seep.</p>" : "") + rows +
      '<div class="rowBtns"><button class="btn" data-act="go" data-step="sim">Simulate this plan &rarr;</button><button class="btn ghost" data-act="csv">Download CSV</button></div>';
    $("budgetExtra").innerHTML =
      more("Field checklist", "<ol class=\"todo\">" +
        "<li><b>Walk the " + plan.funded.length + " funded segments (" + U.num(plan.km, 1) + " km).</b> Strike any that are lined or piped.</li>" +
        "<li><b>Order sealant for " + U.num(plan.sqft) + " sq ft</b> (" + a.wetted_width_ft + " ft wetted width assumed): " + U.usd(plan.spent) + ". Labour and equipment are extra.</li>" +
        "<li><b>" + P.crews + (P.crews === 1 ? " crew" : " crews") + ", about " + U.workTime(total.days) + ",</b> done before first irrigation (early March).</li>" +
        "<li><b>Measure flow in and out</b> of a sealed stretch before paying for the next application (" + a.days_one_application_lasts + " days each).</li></ol>") +
      '<p class="fn">An estimate from published figures, not a field result. Crew speed is our assumption. ' + U.esc(HG.plan.note) + "</p>";
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
    ["applications", 1, 3, 1, (v) => v],
  ];

  /* What the engine needs for the current scope: its weekly record, its canals and the money at stake. */
  function simScope(d) {
    if (d === undefined) d = district();
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

  /* The Simulation step has three small steps of its own, shown as chips on the stage:
       1 District   pick one district (the state view lists them all, with what acting saves in each)
       2 Scenario   pick a future: best, average or worst of the 300, or the real 2020 to 2025 record
       3 Simulation watch that district twice, side by side */
  const CASES = [
    { key: "best", name: "Best case", tone: "low", note: "9 in 10 of the 300 futures are harsher than this one" },
    { key: "likely", name: "Average case", tone: "watch", note: "the middle one of the 300 futures" },
    { key: "worst", name: "Worst case", tone: "warning", note: "9 in 10 of the 300 futures are milder than this one" },
    { key: "check", name: "The real record", tone: "accent", note: "2020 to 2025 as it happened: years the forecast model never saw" },
  ];
  const caseOf = (key) => CASES.find((c) => c.key === key);
  function renderSim() {
    const d = district(), p = params();
    $("view").innerHTML =
      "<h2>" + (d ? "Simulation" : "Simulation: choose a district") + "</h2>" +
      '<div class="sub">' + U.esc(scopeName()) + " · do nothing against sealing when the forecast warns · same weather, reservoir and prices on both sides</div>" +
      '<div id="simLead"></div>' +
      '<div class="controls"><div class="field"><label for="simBudget">Sealing budget, each application <output id="simBudgetOut"></output></label><input id="simBudget" type="range" min="0" max="' + maxBudget() + '" step="' + budgetStep() + '" value="' + state.budget + '"></div><div id="shockRow"></div></div>' +
      '<div id="simResult"></div>' +
      '<details class="more"><summary>Assumptions (' + SLIDERS.length + " sliders)</summary>" +
      SLIDERS.map(([k, min, max, step, show]) => '<div class="field"><label for="a_' + k + '"><span>' + E.DEFAULTS[k].label + ' <span class="tag ' + E.DEFAULTS[k].tag + '">' + E.DEFAULTS[k].tag + '</span></span><output id="o_' + k + '">' + show(p[k]) + '</output></label><input type="range" data-param="' + k + '" id="a_' + k + '" min="' + min + '" max="' + max + '" step="' + step + '" value="' + p[k] + '"></div>').join("") +
      '<button class="btn small ghost" data-act="resetAssume">Reset to defaults</button></details>' +
      '<div id="simNotes"></div>';
    renderSimResult();
  }
  /* The chips and the prompt drawn over the stage on the Simulation step. */
  function simChrome() {
    const d = district(), n = state.simStep;
    $("simSteps").innerHTML = [[1, "District"], [2, "Scenario"], [3, "Simulation"]].map(([k, name]) =>
      '<button data-sim="' + k + '" class="' + (k === n ? "on" : "") + '"' + (k > 1 && !d ? " disabled" : "") + "><b>" + k + "</b>" + name + "</button>").join("");
    $("simPrompt").innerHTML = n === 1 ? "<b>Choose a district</b><span>On the map or in the table. " + HG.districts.length + " districts.</span>"
      : n === 2 ? "<b>" + U.esc(d.name) + "</b><span>Choose a scenario</span>" : "";
  }
  $("simSteps").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b || b.disabled) return;
    const k = Number(b.dataset.sim);
    if (k === 1) { if (district()) setScope(STATE, true); return; }
    state.simStep = k; refresh(k === 2);
  });
  $("simCards").addEventListener("click", (e) => {
    const b = e.target.closest("[data-case]");
    if (b) { state.simCase = b.dataset.case; state.simStep = 3; refresh(false); }
  });

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

  /* Hand the two futures (do nothing, act on the forecast) to the twin picture, week by week. */
  let twinWeeks = [];
  function loadTwin(nothing, act, scope, P, plan, which, note) {
    const flat = (run) => [].concat.apply([], run.years.map((y) => y.weekly));
    const a = flat(nothing), b = flat(act), sums = [{ spend: 0, loss: 0, saved: 0, recovered: 0 }, { spend: 0, loss: 0, saved: 0, recovered: 0 }];
    const add = (sum, w) => { sum.spend += w.spend; sum.loss += w.loss; sum.saved += w.saved; sum.recovered += w.recovered; return Object.assign({}, sum); };
    twinWeeks = a.map((w, i) => ({ date: w.date, pct: w.pct == null ? 0 : w.pct, demand: w.demand, left: w, right: b[i], sumL: add(sums[0], w), sumR: add(sums[1], b[i]) }));
    $("simSeek").max = twinWeeks.length - 1;
    const funded = new Set(plan.funded.map((c) => c.id));
    twin.load({
      rings: district().rings,
      canals: U.canals.filter((c) => c.district === state.scope).map((c) => ({ line: c.line, km: c.km, rate: c.rate, level: c.level, ranked: c.rank != null, funded: funded.has(c.id) })),
      weeks: twinWeeks, caseName: which.name, caseNote: note, tone: which.tone, system: scope.system, fullAt: P.fullAt, cut: P.cut,
      sealedWord: U.theme() === "dark" ? "white" : "black", leftName: "Do nothing", rightName: "Act on the forecast", leftNote: "no canal work", rightNote: "seals when the forecast warns",
    });
  }
  const twin = window.HGTwin.create({ canvas: $("twin"), stage: $("stage"), onTick(i, playing) {
    const w = twinWeeks[i]; if (!w) return;
    $("simSeek").value = i; $("simPlay").textContent = playing ? "Pause" : (i >= twinWeeks.length - 1 ? "Run again" : "Play");
    $("simDate").textContent = "Week of " + U.niceDate(w.date);
  } });
  $("simPlay").onclick = () => (twin.playing() ? twin.pause() : twin.play());
  $("simSkip").onclick = () => { twin.pause(); twin.seek(twinWeeks.length - 1); };
  $("simSeek").oninput = (e) => { const i = Number(e.target.value); twin.pause(); twin.seek(i); };   // read the slider first: pausing redraws it

  /* The three scenario cards (and the real-record card) shown over the map on sub-step 2. */
  function buildCards(run, check, endYear) {
    const spark = (weeks) => {                                  // reservoir storage, week by week, as a small line
      const pts = weeks.map((w, i) => (300 * i / (weeks.length - 1)).toFixed(1) + "," + (33 - Math.max(0, Math.min(100, w.pct || 0)) * 0.3).toFixed(1)).join(" ");
      return '<svg viewBox="0 0 300 34" preserveAspectRatio="none" aria-hidden="true"><polyline points="0,33 300,33" fill="none" stroke="currentColor" stroke-opacity=".25"/><polyline points="' + pts + '" fill="none" stroke="var(--river)" stroke-width="2"/></svg>';
    };
    const flat = (r) => [].concat.apply([], r.years.map((y) => y.weekly));
    $("simCards").innerHTML = CASES.map((c) => {
      const pair = c.key === "check" ? [check[0], check[2]] : [run.cases[c.key].sample[0], run.cases[c.key].sample[2]];
      const gain = pair[0].totals.cost - pair[1].totals.cost;
      return '<button class="scase ' + c.key + '" data-case="' + c.key + '"><h3>' + c.name + "<small>" + (c.key === "check" ? "2020 to 2025" : "to " + endYear) + "</small></h3>" +
        '<div class="big">' + money(pair[0].totals.loss) + "</div><p>in crops lost if nothing is done. " + c.note.charAt(0).toUpperCase() + c.note.slice(1) + ".</p>" + spark(flat(pair[0])) +
        '<p class="tiny">reservoir storage, week by week</p><div class="gain ' + (gain >= 0 ? "" : "bad") + '">Acting ' + (gain >= 0 ? "saves " + money(gain) : "costs " + money(-gain) + " more") + '</div><div class="go">Run this scenario &rarr;</div></button>';
    }).join("");
  }

  /* State view: every district, with what acting on the forecast saves it in the middle future.
     Each district is run on its own canals with every treatable canal funded. */
  let tableCache = null, tableKey = "";
  function districtTable(over, hit, on) {
    const key = JSON.stringify([over, state.live && state.live.systems, on.map((s) => s.key)]);
    if (key !== tableKey) {
      const median = (list) => list.slice().sort((a, b) => a - b)[Math.floor(list.length / 2)];
      tableCache = HG.districts.map((d, i) => {
        const scope = simScope(d), res = reservoirFor(d);
        const budget = scope.canals.reduce((s, c) => s + c.usd, 0) + 1;
        const r = E.fromToday(scope, [{ trigger: "never" }, { trigger: "forecast" }], Object.assign({}, over, { budget }), {
          startDate: TODAY, pctNow: res.pct == null ? 50 : res.pct, pNow: scope.pNow, years: 5, draws: 100, seed: 11, cutoffYear: 2020,
          recall: hit.recall, falseAlarm: hit.falseAlarm, shocks: on.filter((x) => x.shock).map((x) => x.shock), secondDryYear: on.some((x) => x.secondDryYear) });
        return { d, i, loss: r.policies[0].summary.loss.mid, saved: median(r.policies[1].draws.map((t, k) => r.policies[0].draws[k].cost - t.cost)) };
      }).sort((a, b) => b.saved - a.saved);
      tableKey = key;
    }
    return "<h3>Five-year result by district, middle future</h3><div class=\"scroll\"><table class=\"t\"><tr><th>District</th><th class=\"r\">Canals</th><th class=\"r\">Do nothing loses</th><th class=\"r\">Acting saves</th></tr>" +
      tableCache.map((r) => '<tr class="go" data-act="district" data-i="' + r.i + '"><td>' + U.esc(r.d.name) + ' <span class="muted">' + r.d.counties.join(", ") + '</span></td><td class="r">' + U.num(r.d.canalKm) + ' km</td><td class="r">' + money(r.loss) + '</td><td class="r save">' + money(r.saved) + "</td></tr>").join("") +
      '</table></div><p class="fn">Middle of 100 futures per district, every rankable canal funded. Select a row to watch that district.</p>';
  }

  function renderSimResult() {
    const scope = simScope(), over = Object.assign({}, state.overrides, { budget: state.budget }), P = E.makeParams(over);
    $("simBudgetOut").textContent = U.usd(state.budget);
    const plan = E.fundCanals(scope.canals, state.budget, P), planN = U.canalNumbers(plan.funded, P);
    const li = (cls, text, tag) => '<li class="' + cls + '">' + text + (tag ? ' <span class="tag ' + tag + '">' + tag + "</span>" : "") + "</li>";
    const who = scope.members > 1 ? scope.members + " districts on the " + scope.system + " system" : "this district";
    let html = "<h3>What acting means each year you act</h3>" + triple(planN);
    const d = district(), which = caseOf(state.simCase), hit = hitRates(), on = SHOCKS.filter((s) => state.shocks[s.key]);
    const showCheck = d && state.simStep === 3 && state.simCase === "check";
    // The real 2020 to 2025 record, with the forecasts the frozen model made for those years.
    const test = Object.assign({}, scope, { weeks: scope.weeks.filter((w) => w.year >= 2020 && w.year <= 2025) });
    const runs = POLICIES.map((pol) => E.simulate(test, { trigger: pol.trigger }, over));
    const endYear = Number(TODAY.slice(0, 4)) + 5;
    let run = null, lead = "";

    if (!showCheck) {
      const res = reservoirFor(district());
      run = E.fromToday(scope, POLICIES.map((pol) => ({ trigger: pol.trigger })), over, {
        startDate: TODAY, pctNow: res.pct == null ? 50 : res.pct, pNow: scope.pNow, years: 5, draws: 300, seed: 11,
        cutoffYear: 2020, recall: hit.recall, falseAlarm: hit.falseAlarm,
        shocks: on.filter((s) => s.shock).map((s) => s.shock), secondDryYear: on.some((s) => s.secondDryYear) });
      const base = run.policies[0].draws;
      // The headline: what acting saves in the middle future, and what each sealant dollar returns.
      const median = (list) => list.slice().sort((a, b) => a - b)[Math.floor(list.length / 2)];
      const actDraws = run.policies[2].draws;
      const saved = median(actDraws.map((t, k) => base[k].cost - t.cost)), kept = median(actDraws.map((t, k) => base[k].loss - t.loss));
      const spent = run.policies[2].summary.spend.mid, behind = actDraws.filter((t, k) => t.cost > base[k].cost).length;
      // The same question at other budgets (fewer futures, to stay quick): does more sealing still pay?
      const top = maxBudget(), levels = [0, 0.1, 0.25, 0.5, 0.75, 1].map((f) => Math.round(top * f));
      const curve = levels.map((b) => {
        if (b === 0) return 0;
        const r = E.fromToday(scope, [{ trigger: "never" }, { trigger: "forecast" }], Object.assign({}, over, { budget: b }), {
          startDate: TODAY, pctNow: res.pct == null ? 50 : res.pct, pNow: scope.pNow, years: 5, draws: 120, seed: 11, cutoffYear: 2020,
          recall: hit.recall, falseAlarm: hit.falseAlarm, shocks: on.filter((x) => x.shock).map((x) => x.shock), secondDryYear: on.some((x) => x.secondDryYear) });
        return median(r.policies[1].draws.map((t, k) => r.policies[0].draws[k].cost - t.cost));
      });
      const mult = U.PUBLISHED.worstCaseOutput / U.PUBLISHED.worstCaseRevenue;      // total economic output per $1 of crop revenue (Texas A&M)
      const heroHtml = '<div class="saveHero"><span>Net saving to ' + endYear + ", middle of 300 futures</span><b>" + money(saved) + "</b></div>" +
        stats([
          ["Crop revenue kept", money(kept), "net farm revenue"],
          ["Economic output kept", money(kept * mult), "Texas A&amp;M multiplier, " + mult.toFixed(1) + "x"],
          ["Sealant spent", money(spent), spent > 0 ? "$" + U.num(kept / spent) + " kept per $1" : ""],
          ["Futures where acting loses", behind + " / 300", "false alarms cost a round of sealing"],
        ]);
      const curveHtml = "<h3>Net saving by budget</h3><div class=\"chart\">" +
        lineChart([{ name: "Five-year net saving, middle future", color: U.TIER_COLOR.Low, values: curve }], levels.map((b) => money(b)), money) + "</div>" +
        (state.budget < top ? '<div class="rowBtns"><button class="btn small" data-act="fullBudget">Fund every rankable canal: ' + U.usd(top) + "</button></div>" : "");
      const policyRows = POLICIES.map((pol, i) => {
        const c = run.policies[i].summary.cost, gains = run.policies[i].draws.map((t, k) => base[k].cost - t.cost).sort((a, b) => a - b);
        return "<tr><td>" + pol.name + '</td><td class="r">' + money(c.mid) + '</td><td class="r muted">' + money(c.low) + " to " + money(c.high) + '</td><td class="r save">' + (i ? money(gains[Math.floor(gains.length / 2)]) : "") + '</td><td class="r">' + (i ? gains.filter((g) => g < 0).length : "") + "</td></tr>";
      }).join("");
      const keptYear = E.savedAcreFeet(plan.gallonsPerDay, Math.min(273, P.daysLast * P.applications), P.cut);
      html = '<p class="fn">Start ' + U.niceDate(TODAY) + " · " + scope.system + " " + (res.pct == null ? "n/a" : res.pct + "%") + " (" + (res.live ? "live" : "saved") + ") · drought chance " + U.pct(scope.pNow) +
        (FROZEN ? " from a model frozen at " + U.niceDate(FROZEN.trainedOn.to) : "") + " · futures drawn from " + run.libraryYears.length + " real years, " + run.libraryYears[0] + " to " + run.libraryYears[run.libraryYears.length - 1] + " (" + run.dryYears.length + " dry)" +
        (on.length ? " · <b>added: " + on.map((s) => s.label.toLowerCase()).join(", ") + "</b>" : "") + ".</p>" + heroHtml +
        "<h3>One application</h3>" + triple(planN) + '<p class="fn">' + P.applications + (P.applications === 1 ? " application" : " applications") + " in a season you act, about " + Math.min(9, 3 * P.applications) + " months sealed.</p>" + curveHtml +
        "<h3>Total cost to " + endYear + ": crops lost plus sealing</h3><table class=\"t\"><tr><th>Policy</th><th class=\"r\">Middle</th><th class=\"r\">8 in 10 futures</th><th class=\"r\">Saves</th><th class=\"r\">Worse in</th></tr>" + policyRows + "</table>" +
        '<p class="fn">For ' + who + ". Declaration: 8 straight weeks at D2, then " + P.paperworkWeeks + " weeks of paperwork.</p>" +
        more("Reservoir storage in the 300 futures", '<div class="chart">' +
          lineChart([{ name: "Middle future", color: U.TIER_COLOR.Low, values: run.fan.map((w) => w.mid) },
                     { name: "Full supply above", color: U.LEVEL_COLOR["Unknown soil"], values: run.fan.map(() => P.fullAt), dash: true },
                     { name: "No supply below", color: U.TIER_COLOR.Warning, values: run.fan.map(() => P.zeroAt), dash: true }],
                    run.fan.map((w) => w.date.slice(0, 4)), (v) => Math.round(v) + "%", { low: run.fan.map((w) => w.low), high: run.fan.map((w) => w.high), color: U.TIER_COLOR.Low }) + '</div><p class="fn">Band: 8 in 10 futures. Starts at today\'s reading.</p>') +
        more("Read before quoting", "<ul class=\"plain\">" +
          "<li>The forecast warns before " + Math.round(hit.recall * 100) + "% of dry seasons and before " + Math.round(hit.falseAlarm * 100) + "% of wet ones (test on 2020 to 2025). A wrong warning costs " + U.usd(plan.spent * P.applications) + ".</li>" +
          "<li>Saved water only counts in a shortage, and never exceeds the water released that week. Over " + P.fullAt + "% storage, sealing earns nothing.</li>" +
          "<li>In a year you act the model keeps " + U.num(keptYear) + " acre-feet here. Published potential for 28 Valley districts is 54,000 to 223,000 a year (Fipps, 1998). The model assumes every canal is unlined and wet all season, so treat the saving as an upper estimate.</li>" +
          "<li>Sealant strength is the middle of field tests (28% to 87%). It has not been tested on the Rio Grande.</li></ul>");
    } else {
      const d1 = E.simulate(test, { trigger: "d1" }, over), always = E.simulate(test, { trigger: "always" }, over);
      const [nothing, react, act] = runs, years = nothing.years.map((y) => y.year);
      const diff = (a, b) => a.totals.cost - b.totals.cost;
      const better = (v, other) => (Math.abs(v) < 0.002 * act.totals.cost ? "ended level with " + other : v > 0 ? "ended " + money(v) + " ahead of " + other : "ended " + money(-v) + " behind " + other);
      const t = FROZEN && FROZEN.test.preSeason;
      html = '<p class="fn">A test, not a forecast: the model was frozen at ' + (FROZEN ? U.niceDate(FROZEN.trainedOn.to) : "2019") + " and is run on the real record after it.</p>" + "<h3>One application</h3>" + triple(planN) +
        "<h3>Total cost, 2020 to 2025</h3><table class=\"t\"><tr><th>Policy</th><th class=\"r\">Crops lost</th><th class=\"r\">Sealing</th><th class=\"r\">Total</th><th class=\"r\">Saves</th></tr>" + POLICIES.map((pol, i) => {
          const tt = runs[i].totals;
          return "<tr><td>" + pol.name + '</td><td class="r">' + money(tt.loss) + '</td><td class="r">' + money(tt.spend) + '</td><td class="r">' + money(tt.cost) + '</td><td class="r save">' + (i ? money(nothing.totals.cost - tt.cost) : "") + "</td></tr>";
        }).join("") + "</table>" +
        '<p class="fn">For ' + who + ".</p>" +
        "<h3>Running gain over doing nothing</h3><div class=\"chart\">" +
        lineChart(POLICIES.slice(1).map((pol, i) => { let sum = 0; return { name: pol.name, color: i ? U.LEVEL_COLOR.Low : U.TIER_COLOR.Watch, values: runs[i + 1].years.map((y, k) => (sum += nothing.years[k].loss - y.loss - y.spend)) }; }), years, money) +
        '</div><p class="fn">Crop loss avoided minus sealing cost. Flat in wet years.</p>' +
        (t ? "<h3>Forecast accuracy, January to March warnings</h3><div class=\"scroll\" style=\"max-height:none\"><table class=\"t\"><tr><th>Rule</th><th class=\"r\">Drought seasons caught</th><th class=\"r\">Warnings that were right</th></tr>" +
          "<tr><td><b>Our forecast</b> (trained before 2020)</td><td class=\"r\">" + t.forecast.caught + " of " + t.forecast.droughtSeasons + " (" + Math.round(t.forecast.recall * 100) + "%)</td><td class=\"r\">" + Math.round(t.forecast.precision * 100) + "%</td></tr>" +
          "<tr><td>Simple rule: already in moderate drought</td><td class=\"r\">" + t.d1Rule.caught + " of " + t.d1Rule.droughtSeasons + " (" + Math.round(t.d1Rule.recall * 100) + "%)</td><td class=\"r\">" + Math.round(t.d1Rule.precision * 100) + "%</td></tr></table></div>" +
          '<p class="fn">' + t.forecast.rows + " county-months, 14 Texas river counties, " + U.niceDate(FROZEN.test.from) + " to " + U.niceDate(FROZEN.test.to) + ". The two are close.</p>" : "") +
        "<h3>Result</h3><ul class=\"plain\">" +
        li(diff(nothing, act) >= 0 ? "for" : "against", "<b>Acting on the forecast " + better(diff(nothing, act), "doing nothing") + ".</b> It sealed in " + act.totals.yearsActed + " of " + years.length + " years.", "assumption") +
        li(diff(react, act) > 0 ? "for" : "against", "<b>Acting on the forecast " + better(diff(react, act), "waiting for a declaration") + ".</b> Waiting sealed in " + react.totals.yearsActed + " years.", "assumption") +
        li(diff(d1, act) > 0 ? "for" : "against", "<b>The forecast " + better(diff(d1, act), "the simple rule \"seal if already in moderate drought\"") + ".</b>", "pipeline") +
        li(diff(always, act) > 0 ? "for" : "against", "<b>The forecast " + better(diff(always, act), "sealing every single year") + ".</b> Sealant is cheap next to lost crops, so sealing every year is hard to beat.", "assumption") +
        li("against", "<b>False alarms: " + act.totals.falseAlarms + " of " + act.totals.yearsActed + " years acted.</b> In those years sealing was paid for and there was no shortage for the saved water to fill.", "pipeline") +
        "</ul>";
    }

    // What the stage shows, and the few lines that lead the panel, for the current sub-step.
    if (!d) lead = districtTable(over, hit, on);
    else if (state.simStep === 2) {
      buildCards(run, runs, endYear);
      lead = '<p class="fn">Cards on the map: the mild, middle and harsh futures of 300, ranked by what doing nothing costs here, and the real 2020 to 2025 record.</p>';
    } else {
      const pair = showCheck ? [runs[0], runs[2]] : [run.cases[which.key].sample[0], run.cases[which.key].sample[2]];
      const gain = pair[0].totals.cost - pair[1].totals.cost;
      const note = showCheck ? "The real record: real drought, real reservoir levels, the forecasts the frozen model made"
                             : "Weather borrowed from " + run.cases[which.key].sourceYears.join(", ") + ", started from today's reservoir level";
      loadTwin(pair[0], pair[1], scope, P, plan, which, note);
      lead = '<p class="watching ' + which.key + '"><b>' + which.name + ".</b> " + note + ".</p>" +
        stats([
          ["Do nothing, crops lost", money(pair[0].totals.loss), ""],
          ["Act, crops lost", money(pair[1].totals.loss), money(pair[1].totals.spend) + " sealing, " + pair[1].totals.yearsActed + " of " + pair[1].years.length + " years"],
          ["Net saving, this future", (gain >= 0 ? "" : "-") + money(Math.abs(gain)), U.num(plan.funded.length) + " segments sealed, " + U.num(plan.km, 1) + " km"],
        ]) +
        '<p class="fn">Green fields have water, brown fields do not; bright green on the right are fields that sealing kept watered. The dry share is the model\'s number; which squares are dry is illustration.</p>';
    }
    $("simLead").innerHTML = lead;
    $("shockRow").innerHTML = showCheck ? "" : '<div class="shocks"><span>Stress tests (our assumptions):</span>' + SHOCKS.map((s) => '<button class="sbtn ' + (state.shocks[s.key] ? "on" : "") + '" data-shock="' + s.key + '" title="' + s.note + '">' + s.label + "</button>").join("") + "</div>";
    $("simResult").innerHTML = html;

    $("simNotes").innerHTML =
      (scope.outsideValley ? '<p class="fn warn">The published farm-loss figure covers only Cameron, Hidalgo, Starr and Willacy counties. Applying its value per acre-foot here is our extrapolation.</p>' : "") +
      (!district() ? '<p class="fn">The state run covers the districts on the Amistad-Falcon system. El Paso and Hudspeth districts draw on Elephant Butte; open one of them to simulate it.</p>' : "") +
      '<details class="more"><summary>Sources and method</summary><div class="src">' +
      '<p><span class="tag published">published</span> A year with no irrigation water costs the Valley ' + U.usd(U.PUBLISHED.worstCaseRevenue) + ' in net crop revenue and 8,404 jobs (<a target="_blank" rel="noopener" href="' + U.PUBLISHED.worstCaseUrl + '">Texas A&amp;M AgriLife, 2023</a>). Full irrigation demand is 1,349,369 acre-feet a year (<a target="_blank" rel="noopener" href="' + U.PUBLISHED.valleyIrrigationUrl + '">Region M Water Plan, Table 2-8</a>, 2011 use). Dividing the two gives about $367 per acre-foot; that division is ours.</p>' +
      '<p><span class="tag assumption">assumption</span> This scope holds ' + Math.round(scope.share * 100) + "% of the Valley districts' canal length, so it is given that share of the water and of the revenue: " + U.usd(scope.revenueAtStake) + " a year at stake.</p>" +
      '<p><span class="tag assumption">assumption</span> How much water farms get is read off reservoir storage with a straight line between two of the sliders above. The real rule is an accounting of reserves (<a target="_blank" rel="noopener" href="' + U.PUBLISHED.allocationRule.url + '">' + U.PUBLISHED.allocationRule.text + "</a>): cities are served first and irrigation gets what is left.</p>" +
      '<p><span class="tag pipeline">pipeline</span> Drought classes and reservoir levels are the real weekly records. "Declaration" uses the federal fast-track rule: 8 straight weeks at D2 (<a target="_blank" rel="noopener" href="' + U.PUBLISHED.disasterRule.url + '">' + U.PUBLISHED.disasterRule.text + "</a>).</p>" +
      '<p style="margin:0"><span class="tag assumption">assumption</span> Sealing is one application of sealant on unlined canals, materials only, and it has not been field-tested on the Rio Grande. Crew speed is our own guess. Permanent lining is a different job: one 3,900-foot main-canal project was budgeted at $5.1 million (<a target="_blank" rel="noopener" href="' + U.PUBLISHED.liningExample.url + '">' + U.PUBLISHED.liningExample.text + "</a>).</p></div></details>";
  }

  /* ---------- Putting it together ---------- */
  function refresh(refit) {
    document.querySelectorAll("#stepper button").forEach((b) => b.classList.toggle("on", b.dataset.step === state.step));
    const sim = state.step === "sim";
    if (sim) state.simStep = district() ? Math.max(2, state.simStep) : 1;      // the state view can only pick a district
    $("stage").classList.toggle("flow", sim);                                   // chips and prompt over the stage
    $("stage").classList.toggle("cards", sim && state.simStep === 2);           // the scenario cards
    $("stage").classList.toggle("sim", sim && state.simStep === 3);             // the twin picture instead of the map
    if (sim) simChrome();
    $("scopeBtn").innerHTML = "<small>" + (district() ? "District" : "View") + "</small>" + U.esc(scopeName()) + " &#9662;";
    $("viewScope").textContent = district() ? "My district" : "All of Texas";
    ({ risk: renderRisk, budget: renderBudget, sim: renderSim })[state.step]();
    syncMap();
    $("view").scrollTop = 0;
    if (sim && state.simStep === 3) twin.play(); else twin.pause();
    if (refit && !map.isScanning()) map.fitScope();
  }
  function setScope(scope, noScan) {
    state.scope = scope; state.county = null; state.canal = null; state.severity = null; state.simStep = 2;
    state.budget = defaultBudget();
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
    if (act === "fullBudget") { state.budget = maxBudget(); renderSim(); }
    if (act === "canal") { state.canal = Number(t.dataset.id); map.flyToCanal(state.canal); refresh(false); }
  });
  $("lightbox").onclick = () => $("lightbox").classList.remove("on");
  $("view").addEventListener("click", (e) => {
    const sev = e.target.closest("#sev button"), shock = e.target.closest("[data-shock]");
    if (sev) { state.severity = sev.dataset.p === "" ? null : Number(sev.dataset.p); renderBudget(); }
    if (shock) { state.shocks[shock.dataset.shock] = !state.shocks[shock.dataset.shock]; renderSimResult(); if (state.simStep === 3) twin.play(); }
  });
  $("view").addEventListener("input", (e) => {
    if (e.target.id === "budget") { state.budget = Number(e.target.value); renderBudgetResult(); }
    if (e.target.id === "simBudget") { state.budget = Number(e.target.value); renderSimResult(); if (state.simStep === 3) twin.play(); }
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
    map.readTheme(); twin.readTheme(); refresh(false);
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
  function openChooser() { fillPick(""); $("pickSearch").value = ""; $("pick").classList.add("open"); $("onboard").classList.add("open"); }
  $("roleState").addEventListener("click", () => setScope(STATE));
  $("roleDistrict").addEventListener("click", () => { $("pickSearch").focus(); $("pick").scrollIntoView({ behavior: "smooth" }); });
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
  // There is no sign-in, so every visit starts by asking who you are and which district.
  // A link that names a scope (#state or #d=District name) skips the question.
  const byName = (name) => HG.districts.findIndex((d) => d.name === name);
  const hash = decodeURIComponent(location.hash.slice(1));
  if (location.search.indexOf("step=") >= 0) state.step = location.search.split("step=")[1].split("&")[0];   // for links straight to a step
  if (hash === "state") setScope(STATE);
  else if (hash.indexOf("d=") === 0 && byName(hash.slice(2)) >= 0) setScope(byName(hash.slice(2)));
  else { state.scope = STATE; state.budget = defaultBudget(); refresh(true); openChooser(); }
})();
