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
  const L = U.logic;                                    // the rules with no page code (js/logic.js), bound to the data
  const { gal, money, usesElephantButte, safeUrl, cssClass, finiteOrNull, percentOrNull, band, rangeText, rangeCell } = window.HGLogic, hitRates = L.hitRates;
  const $ = (id) => document.getElementById(id);
  const STATE = -1;
  const FROZEN = SIM.pre2020;                           // the forecast model trained only on data before 2020
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

  const state = { scope: null, step: "risk", mapMode: "now", budget: null, severity: null, simStep: 2, simCase: "likely", simSel: null,
                  overrides: {}, county: null, canal: null, live: null, shocks: {} };

  /* ---------- Scope helpers ---------- */
  const district = () => (state.scope >= 0 ? HG.districts[state.scope] : null);
  const scopeCanals = () => (state.scope >= 0 ? U.canals.filter((c) => c.district === state.scope)
                                              : U.canals.filter((c) => c.district >= 0));
  const scopeName = () => (district() ? district().name : "State of Texas");
  const params = () => E.makeParams(state.overrides);
  /* The chance of a drought season used by the planner: the "what if" value, or the forecast. */
  function scopeP() { return L.scopeP(state.severity, district()); }
  function scopeP0() { const keep = state.severity; state.severity = null; const p = scopeP(); state.severity = keep; return p; }
  /* Today's reading for one reservoir system from api/live, or null if there is none or its
     figure is not a percentage (then the page keeps, and says it shows, the saved reading). */
  function liveReading(name) {
    const reading = state.live && state.live.systems && state.live.systems[name];
    return reading && percentOrNull(reading.pct) != null ? reading : null;
  }
  function reservoirFor(d) {
    const name = d && usesElephantButte(d) ? "Elephant Butte" : "Amistad-Falcon";
    const county = HG.river.find((c) => c.reservoir === name);
    let pct = county ? finiteOrNull(county.reservoirPct) : null, date = HG.week, live = false;
    // A live reading is used only if its figure is a real number from 0 to 100; otherwise the saved one stays.
    const reading = liveReading(name);
    if (reading) { pct = reading.pct; date = reading.date; live = true; }
    return { name, pct, date, live };
  }

  /* ---------- Small HTML pieces ---------- */
  const kpi = (label, value, small) => '<div class="kpi"><span>' + label + "</span><b>" + value + "</b>" + (small ? "<small>" + small + "</small>" : "") + "</div>";
  const chip = (tier, text) => '<span class="chip ' + cssClass(tier, window.HGLogic.TIER_CLASSES) + '"><i></i>' + U.esc(text || tier) + "</span>";
  /* A link that opens in a new tab. The address must start with https:// or http://; if it does
     not, only the text is shown. hrefFirst only sets the order of the attributes. */
  const anchor = (text, url, hrefFirst) => (safeUrl(url) == null ? U.esc(text)
    : (hrefFirst ? '<a href="' + U.esc(url) + '" target="_blank" rel="noopener">' : '<a target="_blank" rel="noopener" href="' + U.esc(url) + '">') + U.esc(text) + "</a>");
  /* Water is shown in gallons, which people can picture: gal() in js/logic.js converts from acre-feet. */
  const af = (n) => gal(n.afLow).replace(/ (million|billion) gal$/, (m, w) => (gal(n.afHigh).indexOf(w) > 0 ? "" : " " + w)) + " to " + gal(n.afHigh);   // a range, e.g. "20 to 63 billion gal"
  const afMid = (n) => gal((n.afLow + n.afHigh) / 2);
  /* A row of key figures: [[label, value, note], ...]. Plain rules between them, no boxes. */
  const stats = (rows) => '<dl class="stats">' + rows.map((r) => "<div class=\"" + (r[3] || "") + "\"><dt>" + r[0] + "</dt><dd>" + r[1] + "</dd>" + (r[2] ? "<small>" + r[2] + "</small>" : "") + "</div>").join("") + "</dl>";
  /* The three numbers every canal decision comes down to. n = U.canalNumbers(...). oneCrew = time for a single crew. */
  function triple(n, oneCrew, cls) {
    const p = params(), days = oneCrew ? n.crewDays : n.days;
    return '<dl class="stats three ' + (cls || "") + '">' +
      '<div class="cost"><dt>Cost</dt><dd>' + (n.usd >= 1e6 ? money(n.usd) : U.usd(n.usd)) + "</dd><small>sealant, " + U.num(n.km, n.km < 10 ? 2 : 1) + " km; labour extra</small></div>" +
      '<div class="time"><dt>Time</dt><dd>' + U.workTime(days) + "</dd><small>" + (oneCrew ? "1 crew" : p.crews + (p.crews === 1 ? " crew" : " crews")) + ", " + p.kmPerCrewDay + " km a day</small></div>" +
      '<div class="save"><dt>Water kept</dt><dd>' + (n.afHigh > 0 ? af(n) : "unknown") + "</dd><small>" + (n.afHigh > 0 ? "per 90-day application; " + money(n.worthLow) + " to " + money(n.worthHigh) + " in a shortage" : "no seepage rate for this soil") + "</small></div></dl>";
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
    const caption = (kind) => (Object.prototype.hasOwnProperty.call(captions, kind) ? captions[kind] : "Photo");
    const photos = c.photos.map((kind) => '<figure><img loading="lazy" src="' + U.esc(U.photo(fips, kind)) + '" alt="' + caption(kind) + " of " + U.esc(c.name) + ' County"><figcaption>' + caption(kind) + "</figcaption></figure>").join("");
    let credit = "Aerial images: USGS The National Map (public domain), from past flights.";
    if (c.credit && c.photos.indexOf("ground") >= 0) {
      credit += " Ground photo: " + anchor(c.credit.what || "photo", c.credit.source, true) + " by " + U.esc(c.credit.by) + ", " + U.esc(c.credit.licence) + ".";
    }
    return '<div class="card">' +
      (closable ? '<button class="back" data-act="closeCounty">&times; Close county</button>' : "") +
      '<div style="display:flex;justify-content:space-between;gap:10px;align-items:baseline"><b style="font-size:1.05rem">' + U.esc(c.name) + " County</b>" +
      (river ? chip(river.tier, river.tier + " · " + U.pct(river.pSeason)) : "") + "</div>" +
      '<div class="small muted" style="margin:2px 0 8px">Drought now: ' + (c.dm == null ? "no data" : U.DM_TEXT[c.dm]) +
      (c.pop ? " · Population (2020): " + U.num(c.pop) : "") +
      (river ? " · Expected drought weeks in the next year: " + U.esc(river.weeksLow) + " to " + U.esc(river.weeksHigh) : " · Not a river county, so no forecast") + "</div>" +
      (photos ? '<div class="photos">' + photos + "</div>" : "") +
      (c.about ? '<p class="small" style="margin:0 0 4px">' + U.esc(c.about) + (safeUrl(c.page) == null ? "" : " " + anchor("Wikipedia", c.page, true)) + "</p>" : "") +
      '<div class="credit">' + credit + "</div></div>";
  }
  function issuesFor(d) {
    if (!HG.issues) return "";
    const list = HG.issues.issues.filter((x) => (d ? x.district === d.name || (x.where || []).some((f) => d.fips.indexOf(f) >= 0) : true)).slice(0, d ? 6 : 8);
    if (!list.length) return "";
    return "<h3>Open issues from live data</h3><div class=\"card\">" + list.map((x) =>
      '<div class="issue"><span class="sev ' + cssClass(x.severity, window.HGLogic.SEVERITY_CLASSES) + '"></span><div><b>' + U.esc(x.title) + "</b><br><span class=\"muted\">" + U.esc(x.detail) + "</span><br><span class=\"credit\">Source: " + U.esc(x.source) + " · as of " + U.esc(x.as_of) + "</span></div></div>").join("") +
      '</div><p class="credit">' + U.esc(HG.issues.note) + "</p>";
  }
  function mixBar(list, keyOf, colorOf) {
    const total = {}, km = list.reduce((s, c) => s + c.km, 0) || 1;
    list.forEach((c) => { total[keyOf(c)] = (total[keyOf(c)] || 0) + c.km; });
    const keys = Object.keys(total).sort((a, b) => total[b] - total[a]);
    return '<div class="stack">' + keys.map((k) => '<i title="' + U.esc(k) + '" style="width:' + (100 * total[k] / km) + "%;background:" + U.esc(colorOf(k)) + '"></i>').join("") + "</div>" +
      '<div class="legend">' + keys.slice(0, 6).map((k) => '<span><i style="background:' + U.esc(colorOf(k)) + '"></i>' + U.esc(k) + " " + U.num(total[k]) + " km</span>").join("") + "</div>";
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

  /* Is the state view showing the simulation's district list (where map taps pick districts)? */
  const picking = () => state.step === "sim" && !district() && state.simStep === 1;
  /* With everything ticked (the default), a tap picks just that district. After that, taps add or remove. */
  function tapDistrict(i) {
    if (GROUPABLE.indexOf(i) < 0) { setScope(i); return; }             // an Elephant Butte district opens on its own
    simMembers();
    if (state.simSel.size === GROUPABLE.length) state.simSel = new Set([i]);
    else if (state.simSel.has(i)) state.simSel.delete(i); else state.simSel.add(i);
    renderSimResult(); simChrome();
  }

  /* ---------- The map ---------- */
  const map = window.HGMap.create({
    stage: $("stage"), canvas: $("map"), tip: $("tip"), coords: $("coords"), bar: $("bar"),
    hud: { phase: $("phase"), line1: $("hud1"), line2: $("hud2") },
    // On the simulation's district list, any tap inside a district picks that district:
    // a tap on one of its canals counts, and a tap on empty county land does nothing.
    onCanal: (c) => { if (picking()) { if (c.district >= 0) tapDistrict(c.district); return; } state.canal = c.id; if (state.step === "sim") state.step = "risk"; refresh(false); },
    onDistrict: (i) => { if (picking()) tapDistrict(i); else setScope(i); },
    onCounty: (fips) => { if (picking()) return; state.county = fips; state.canal = null; state.step = "risk"; refresh(false); },
    tipHtml(hit) {
      if (hit.canal) {
        const c = hit.canal, n = U.canalNumbers([c], params());
        return "<b>" + U.esc(c.name) + "</b><dl><dt>Costs</dt><dd class=\"big\">" + U.usd(n.usd) + "</dd><dt>Takes</dt><dd class=\"big\">" + U.workTime(n.crewDays) + "</dd><dt>Saves</dt><dd class=\"big\">" + (n.afHigh > 0 ? af(n) : "unknown") + "</dd>" +
          "<dt>Length</dt><dd>" + U.num(c.km, 2) + " km</dd><dt>Soil</dt><dd>" + U.esc(c.soil || "not looked up") + "</dd><dt>Class</dt><dd>" + U.esc(c.level) + "</dd></dl>" +
          "<small>" + U.esc((c.kind || "Canal or ditch") + (c.piped ? ", mapped as piped" : "") + ". Click for the full card.") + "</small>";
      }
      if (hit.district != null) { const d = HG.districts[hit.district]; return "<b>" + U.esc(d.name) + "</b><dl><dt>Risk</dt><dd>" + U.esc(d.risk) + ", " + U.pct(d.pSeason) + "</dd><dt>Canals</dt><dd>" + U.num(d.canalKm) + " km</dd></dl><small>" + (picking() ? "Tap to select it for the simulation." : "Click to open this district.") + "</small>"; }
      const c = U.countyByFips[hit.county], river = U.riverByFips[hit.county];
      return "<b>" + U.esc(c.name) + " County</b><dl><dt>Drought now</dt><dd>" + (c.dm == null ? "no data" : U.DM_TEXT[c.dm]) + "</dd>" +
        (river ? "<dt>6-month chance</dt><dd>" + U.pct(river.pSeason) + ", " + U.esc(river.tier) + "</dd>" : "") + "</dl><small>Click for photos and a profile.</small>";
    },
  });
  function legend() {
    const forecast = state.mapMode === "forecast", plan = state.step === "budget";
    const key = (color, text) => '<span><i style="background:' + color + '"></i>' + text + "</span>";
    $("legend").innerHTML =
      '<div class="modes"><button data-mode="now" class="' + (forecast ? "" : "on") + '">Drought now</button><button data-mode="forecast" class="' + (forecast ? "on" : "") + '">6-month forecast</button></div>' +
      (forecast ? "<h4>River counties: chance of a drought season</h4><div class=\"keys\">" + ["Low", "Watch", "Warning"].map((t) => key(U.TIER_COLOR[t], t)).join("") + "</div>"
                : "<h4>Drought Monitor, week of " + U.niceDate(HG.week) + '</h4><div class="ramp">' + HG.dmLabels.map((l, i) => '<span><i style="background:' + U.esc(U.DM_COLOR[i]) + '"></i>' + U.esc(l) + "</span>").join("") + "</div>") +
      "<h4>Canals (" + U.num(scopeCanals().length) + " segments here)</h4><div class=\"keys\">" +
      (plan ? key("var(--fund)", "Sealed by this budget") + key("var(--muted)", "Not funded") : HG.levels.map((l) => key(U.esc(U.LEVEL_COLOR[l]), U.esc(l))).join("")) + "</div>";
  }
  $("legend").addEventListener("click", (e) => { const mode = e.target.dataset.mode; if (mode) { state.mapMode = mode; syncMap(); } });
  $("views").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; if (b.dataset.view === "scope") map.fitScope(); else map.flyTo(b.dataset.view); });
  $("zin").onclick = () => map.zoom(1.6); $("zout").onclick = () => map.zoom(1 / 1.6);
  $("replay").onclick = () => map.runScan(); $("skip").onclick = () => map.skip();
  function syncMap() {
    const lakes = {};
    const butte = liveReading("Elephant Butte");
    if (butte) lakes["Elephant Butte"] = butte.pct;
    map.set({ pick: picking(), mode: state.mapMode, scope: state.scope, county: state.county, canal: state.canal,
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
        "<h2>" + U.esc(d.name) + "</h2><div class=\"sub\">" + U.esc(d.kind) + " · " + U.esc(d.counties.join(", ")) + " · week of " + U.niceDate(HG.week) + "</div>" +
        stats([
          ["Drought season, next 6 months", U.pct(d.pSeason), U.esc(d.risk) + "; warning line " + U.pct(HG.threshold)],
          ["Drought now", worst ? "D" + (worst - 1) : "None", U.DM_TEXT[worst].replace(/^D\d /, "")],
          resStat,
          ["Canals", U.num(d.canalKm) + " km", U.num(list.length) + " segments, " + U.num(treatable.length) + " rankable"],
        ]) + gauge(d.pSeason) +
        '<p class="rec ' + act.key + '"><b>' + act.title + ".</b> " + act.text.split(". ").slice(1).join(". ") + "</p>" +
        "<h3>All rankable canals sealed, one application</h3>" + (treatable.length ? triple(all) : '<p class="fn">No canal here can be ranked: drains, or soil with no published seepage rate.</p>') +
        '<div class="rowBtns"><button class="btn" data-act="go" data-step="budget">Budget plan &rarr;</button><button class="btn ghost" data-act="go" data-step="sim">Simulation &rarr;</button></div>' +
        "<h3>Canal length by leak class</h3>" + mixBar(list, (c) => c.level, (k) => U.LEVEL_COLOR[k]) +
        "<h3>Canal length by soil</h3>" + mixBar(list, (c) => c.soil || "Not looked up", (k) => { const r = HG.seepage[k]; return r == null ? U.LEVEL_COLOR["Unknown soil"] : r >= 7.48 ? U.TIER_COLOR.Warning : r >= 2.9 ? U.TIER_COLOR.Watch : U.TIER_COLOR.Low; }) +
        (named.length ? "<h3>Named canals (" + named.length + ")</h3><div class=\"scroll\"><table class=\"t\"><tr><th>Canal</th><th class=\"r\">km</th><th class=\"r\">Cost</th><th class=\"r\">Time</th><th class=\"r\">Water kept</th></tr>" +
          named.slice(0, 80).map((g) => '<tr class="click" data-act="canal" data-id="' + U.esc(g.segs[0].id) + '"><td>' + U.esc(g.name) + ' <span class="muted">(' + g.segs.length + ")</span></td><td class=\"r\">" + U.num(g.km, 1) + "</td>" +
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
          '<tr class="click" data-act="district" data-i="' + U.esc(i) + '"><td>' + U.esc(x.name) + ' <span class="muted">' + U.esc(x.counties.join(", ")) + "</span></td><td>" + chip(x.risk) + '</td><td class="r">' + U.pct(x.pSeason) + '</td><td class="r">' + U.num(x.canalKm) + "</td></tr>").join("") +
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
    const perAf = (x) => (x > 0 ? "$" + U.num(plan.spent / (x * E.GALLONS_PER_ACRE_FOOT / 1e6), 2) : "n/a");   // dollars per million gallons
    let rows;
    if (d) {
      rows = "<h3>Canals in sealing order</h3><div class=\"scroll\"><table class=\"t\"><tr><th>#</th><th>Canal</th><th class=\"r\">km</th><th class=\"r\">Cost</th><th class=\"r\">Time</th><th class=\"r\">Water kept</th></tr>" +
        plan.ordered.slice(0, 250).map((c, i) => { const n = U.canalNumbers([c], P), on = plan.fundedIds.has(c.id); return '<tr class="click ' + (on ? "" : "off") + '" data-act="canal" data-id="' + U.esc(c.id) + '"><td>' + (i + 1) + "</td><td>" + U.esc(c.name) + (c.piped ? '<span class="flag">piped?</span>' : "") + ' <span class="muted">' + U.esc(c.soil) + '</span></td><td class="r">' + U.num(c.km, 2) + '</td><td class="r">' + U.usd(n.usd) + '</td><td class="r">' + U.workTime(n.crewDays) + '</td><td class="r">' + afMid(n) + "</td></tr>"; }).join("") +
        "</table></div><p class=\"fn\">Greyed rows are not funded. One crew; water kept is the middle of the tested range." + (plan.ordered.length > 250 ? " First 250 of " + plan.ordered.length + " shown; the CSV has every funded canal." : "") + "</p>";
    } else {
      const by = {};
      plan.funded.forEach((c) => { (by[c.district] = by[c.district] || []).push(c); });
      const order = Object.keys(by).map((i) => ({ i, n: U.canalNumbers(by[i], P), count: by[i].length })).sort((x, y) => y.n.usd - x.n.usd);
      rows = "<h3>Allocation by district</h3><div class=\"scroll\"><table class=\"t\"><tr><th>District</th><th class=\"r\">Segments</th><th class=\"r\">km</th><th class=\"r\">Cost</th><th class=\"r\">Time</th><th class=\"r\">Water kept</th></tr>" +
        order.map((r) => '<tr class="click" data-act="district" data-i="' + U.esc(r.i) + '"><td>' + U.esc(HG.districts[r.i].name) + '</td><td class="r">' + r.count + '</td><td class="r">' + U.num(r.n.km, 1) + '</td><td class="r">' + U.usd(r.n.usd) + '</td><td class="r">' + U.workTime(r.n.crewDays) + '</td><td class="r">' + afMid(r.n) + "</td></tr>").join("") +
        "</table></div><p class=\"fn\">" + order.length + " of " + HG.districts.length + " districts funded. One crew per district. Select a district for its canal list.</p>";
    }
    $("budgetResult").innerHTML =
      triple(total) +
      stats([
        ["Segments funded", U.num(plan.funded.length), U.num(plan.km, 1) + " km"],
        ["Sealant cost per million gallons kept", perAf(total.afHigh) + " to " + perAf(total.afLow), "a million gallons is worth about $" + U.num(U.USD_PER_AF * 1e6 / E.GALLONS_PER_ACRE_FOOT) + " to farms in a shortage"],
      ]) +
      '<p class="rec ' + act.key + '"><b>' + act.title + ".</b> At a " + U.pct(p) + " chance of a drought season" + (state.severity != null ? " (your setting)." : " (the forecast).") + "</p>" +
      (piped ? '<p class="fn warn">' + piped + " funded segments are mapped as piped in OpenStreetMap. Check them first: a pipe does not seep.</p>" : "") + heldOutNote() + rows +
      '<div class="rowBtns"><button class="btn" data-act="go" data-step="sim">Simulate this plan &rarr;</button><button class="btn ghost" data-act="csv">Download CSV</button></div>';
    $("budgetExtra").innerHTML =
      more("Field checklist", "<ol class=\"todo\">" +
        "<li><b>Walk the " + plan.funded.length + " funded segments (" + U.num(plan.km, 1) + " km).</b> Strike any that are lined or piped.</li>" +
        "<li><b>Order sealant for " + U.num(plan.sqft) + " sq ft</b> (" + U.esc(a.wetted_width_ft) + " ft wetted width assumed): " + U.usd(plan.spent) + ". Labour and equipment are extra.</li>" +
        "<li><b>" + P.crews + (P.crews === 1 ? " crew" : " crews") + ", about " + U.workTime(total.days) + ",</b> done before first irrigation (early March).</li>" +
        "<li><b>Measure flow in and out</b> of a sealed stretch before paying for the next application (" + U.esc(a.days_one_application_lasts) + " days each).</li></ol>") +
      '<p class="fn">An estimate from published figures, not a field result. Crew speed is our assumption. ' + U.esc(HG.plan.note) + "</p>";
    syncMap();
  }
  function downloadCsv() {
    const plan = currentPlan(), P = params();
    const lines = [["order", "canal", "kind", "mapped_as_piped", "district", "county_fips", "soil", "seepage_gal_sqft_day", "km", "sealant_usd", "one_crew_days", "saved_acre_feet_low", "saved_acre_feet_high"].join(",")];
    // Text fields are quoted and kept from being read as formulas; numbers stay numbers (js/logic.js).
    const T = window.HGLogic.csvText, N = window.HGLogic.csvNumber;
    plan.funded.forEach((c, i) => { const n = U.canalNumbers([c], P); lines.push([i + 1, T(c.name), T(c.kind || ""), c.piped ? "yes" : "no", T(c.district >= 0 ? HG.districts[c.district].name : ""), T(c.fips), T(c.soil), N(c.rate), N(c.km), N(n.usd, 2), N(n.crewDays, 2), N(n.afLow, 2), N(n.afHigh, 2)].join(",")); });
    const link = U.el("a", { href: URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" })), download: "canal-sealing-plan.csv" });
    document.body.appendChild(link); link.click(); link.remove();
  }

  /* ---------- Step 3: Simulation ---------- */
  const POLICIES = [
    { trigger: "never", name: "Do nothing", css: "", blurb: "No canal work. Losses are paid for afterwards." },
    { trigger: "declared", name: "Wait for an official drought declaration", css: "react", blurb: "Seal only after 8 straight weeks of severe drought, plus paperwork." },
    { trigger: "forecast", name: "Seal early, when the forecast warns", css: "act", blurb: "Seal before the season whenever the forecast warns." },
  ];
  // The share of seepage the sealant stops is not here: every run draws it from its published
  // range (see unknownsHtml), so a slider for it would do nothing.
  const SLIDERS = [   // the assumptions the user can move: [parameter, min, max, step, how to show it]
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
  /* Where sealing can be simulated: districts with at least one canal that has a seepage rate. */
  const APPLICABLE = HG.districts.map((d, i) => U.canals.some((c) => c.district === i && c.rank != null));
  /* Districts the state view can run TOGETHER: they must share one reservoir system (Amistad-Falcon). */
  const GROUPABLE = HG.districts.map((d, i) => i).filter((i) => APPLICABLE[i] && !usesElephantButte(HG.districts[i]));
  /* The districts being simulated: the open district, or the ones ticked in the state view (all by default). */
  function simMembers() {
    if (district()) return [district()];
    if (!state.simSel) state.simSel = new Set(GROUPABLE);
    return GROUPABLE.filter((i) => state.simSel.has(i)).map((i) => HG.districts[i]);
  }
  function simScope(list) { return L.simScope(list || simMembers()); }
  /* hitRates() (js/logic.js): the frozen model's hit rates on 2020 to 2025, used to decide how often a simulated warning is right. */

  /* The Simulation step has three small steps of its own, shown as chips on the stage:
       1 District   pick one district (the state view lists them all, with what acting saves in each)
       2 Scenario   pick a future: best, average or worst of the 300, or the real 2020 to 2025 record
       3 Simulation watch that district twice, side by side */
  const CASES = [
    { key: "best", short: "Mild", name: "A mild five years", tone: "low", note: "9 in 10 of the 300 futures are harsher than this one" },
    { key: "likely", short: "Typical", name: "A typical five years", tone: "watch", note: "the middle one of the 300 futures" },
    { key: "worst", short: "Harsh", name: "A harsh five years", tone: "warning", note: "9 in 10 of the 300 futures are milder than this one" },
    { key: "check", short: "What really happened, 2020-25", name: "The real record", tone: "accent", note: "2020 to 2025 as it happened: years the forecast model never saw" },
  ];
  const caseOf = (key) => CASES.find((c) => c.key === key);
  function renderSim() {
    const d = district(), p = params();
    if (d && !APPLICABLE[state.scope]) {                       // nothing to seal here, so nothing to simulate
      $("view").innerHTML = "<h2>Simulation</h2><div class=\"sub\">" + U.esc(d.name) + '</div><p class="rec inspect"><b>Not applicable here.</b> None of this district\'s mapped canals has a published seepage rate (they are drains, or sit on soil with no rate), so sealing cannot be costed or simulated.</p>' +
        '<div class="rowBtns"><button class="btn" data-act="state">Choose other districts &rarr;</button></div>';
      return;
    }
    $("view").innerHTML =
      "<h2>Simulation</h2>" +
      '<div class="sub">' + (d ? U.esc(d.name) : simMembers().length === 1 ? U.esc(simMembers()[0].name) : simMembers().length + " districts together") + " · five years, with and without sealing the leakiest canals</div>" +
      '<div id="simLead"></div>' +
      '<div class="controls"><div class="field"><label for="simBudget">Sealant budget, each round <output id="simBudgetOut"></output></label><input id="simBudget" type="range" min="0" max="' + maxBudget() + '" step="' + budgetStep() + '" value="' + state.budget + '"></div><div id="shockRow"></div></div>' +
      '<div id="simResult"></div>' +
      '<details class="more"><summary>Assumptions (' + SLIDERS.length + " sliders, and the unknowns drawn in every run)</summary>" +
      SLIDERS.map(([k, min, max, step, show]) => '<div class="field"><label for="a_' + k + '"><span>' + E.DEFAULTS[k].label + ' <span class="tag ' + E.DEFAULTS[k].tag + '">' + E.DEFAULTS[k].tag + '</span></span><output id="o_' + k + '">' + show(p[k]) + '</output></label><input type="range" data-param="' + k + '" id="a_' + k + '" min="' + min + '" max="' + max + '" step="' + step + '" value="' + p[k] + '"></div>').join("") +
      '<button class="btn small ghost" data-act="resetAssume">Reset to defaults</button><div id="simUnknowns"></div></details>' +
      '<div id="simNotes"></div>';
    renderSimResult();
  }
  /* The chips and the prompt drawn over the stage on the Simulation step. */
  function simChrome() {
    const n = state.simStep;
    $("simSteps").innerHTML = n === 3 ? '<button data-sim="1">&larr; ' + (district() ? "Other districts" : "Back to the district list") + "</button>" : "";
    $("simPrompt").innerHTML = n === 1 ? "<b>Tap a district on the map</b><span>or tick several in the list, then run the simulation</span>" : "";
    // One row of buttons switches scenario.
    $("simCases").innerHTML = CASES.map((c) => '<button class="sbtn ' + (c.key === state.simCase ? "on" : "") + '" data-case="' + c.key + '" title="' + c.note + '">' + c.short + "</button>").join("");
  }
  $("simCases").addEventListener("click", (e) => { const b = e.target.closest("[data-case]"); if (b) { state.simCase = b.dataset.case; refresh(false); } });
  /* Back to the list. From a district's own view, the state list opens with only that district ticked. */
  function backToList() {
    if (district()) { const i = state.scope; setScope(STATE, true); state.simSel = new Set(GROUPABLE.indexOf(i) >= 0 ? [i] : []); }
    state.simStep = 1; refresh(true);
  }
  $("simSteps").addEventListener("click", (e) => { if (e.target.closest("button")) backToList(); });
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
    // Water leaking out of this district's canals in a week, if none were sealed. The rate per
    // square foot comes from each canal's soil (Fipps, Texas A&M, 1998). A canal cannot leak more
    // than the water released into it, and leaks nothing outside the season.
    const leakWeek = E.savedAcreFeet(E.fundCanals(scope.canals, Infinity, P).gallonsPerDay, 7, 1);
    const a = flat(nothing), b = flat(act), blank = () => ({ spend: 0, loss: 0, saved: 0, recovered: 0, leak: 0 }), sums = [blank(), blank()];
    const add = (sum, w) => {
      sum.spend += w.spend; sum.loss += w.loss; sum.saved += w.saved; sum.recovered += w.recovered;
      sum.leak += Math.max(0, Math.min(leakWeek, w.demand - w.missing) - w.saved);      // sealing takes its saving off the leak
      return Object.assign({}, sum);
    };
    twinWeeks = a.map((w, i) => ({ date: w.date, pct: w.pct == null ? 0 : w.pct, demand: w.demand, left: w, right: b[i], sumL: add(sums[0], w), sumR: add(sums[1], b[i]) }));
    $("simSeek").max = twinWeeks.length - 1;
    const funded = new Set(plan.funded.map((c) => c.id));
    twin.load({
      // One part per district. With several districts, each is drawn in its own cell (not to scale).
      parts: scope.ids.map((id) => ({ rings: HG.districts[id].rings, km: HG.districts[id].canalKm,
        canals: U.canals.filter((c) => c.district === id).map((c) => ({ line: c.line, km: c.km, rate: c.rate, level: c.level, ranked: c.rank != null, funded: funded.has(c.id) })) })),
      weeks: twinWeeks, fullAt: P.fullAt,

    });
  }
  // The picture shows single figures for one run. This caption sits on it whenever it is shown
  // (class simOnly: css/site.css shows and hides it together with the picture's canvas).
  const twinCaption = U.el("p", { id: "twinCaption", class: "simOnly" });
  twinCaption.textContent = window.HGLogic.TWIN_CAPTION;
  $("stage").appendChild(twinCaption);
  const twin = window.HGTwin.create({ canvas: $("twin"), stage: $("stage"), onTick(i, playing) {
    const w = twinWeeks[i]; if (!w) return;
    $("simSeek").value = i; $("simPlay").textContent = playing ? "Pause" : (i >= twinWeeks.length - 1 ? "Run again" : "Play");
    $("simDate").textContent = "Week of " + U.niceDate(w.date);
  } });
  $("simPlay").onclick = () => (twin.playing() ? twin.pause() : twin.play());
  $("simSkip").onclick = () => { twin.pause(); twin.seek(twinWeeks.length - 1); };
  $("simSeek").oninput = (e) => { const i = Number(e.target.value); twin.pause(); twin.seek(i); };   // read the slider first: pausing redraws it

  /* State view: every district, with what acting on the forecast saves it in the middle future.
     Each district is run on its own canals with every treatable canal funded. */
  let tableCache = null, tableKey = "";
  function districtTable(over, hit, on) {
    const key = JSON.stringify([over, state.live && state.live.systems, on.map((s) => s.key)]);
    if (key !== tableKey) {
      tableCache = HG.districts.map((d, i) => ({ d, i })).filter((r) => APPLICABLE[r.i]).map(({ d, i }) => {
        const scope = simScope([d]), res = reservoirFor(d);
        const budget = scope.canals.reduce((s, c) => s + c.usd, 0) + 1;
        const r = E.fromToday(scope, [{ trigger: "never" }, { trigger: "forecast" }], Object.assign({}, over, { budget }), {
          startDate: TODAY, pctNow: res.pct == null ? 50 : res.pct, pNow: scope.pNow, years: 5, draws: 100, seed: 11, cutoffYear: 2020,
          recall: hit.recall, falseAlarm: hit.falseAlarm, shocks: on.filter((x) => x.shock).map((x) => x.shock), secondDryYear: on.some((x) => x.secondDryYear),
          physics: true, physicsOptions: L.physicsOptions(), withFixed: false });
        return { d, i, alone: usesElephantButte(d), loss: r.policies[0].summary.loss, saved: band(r.policies[1].draws.map((t, k) => r.policies[0].draws[k].cost - t.cost)) };
      }).sort((a, b) => b.saved.mid - a.saved.mid);
      tableKey = key;
    }
    const n = simMembers().length, q = (state.simQuery || "").toLowerCase();
    const rows = tableCache.filter((r) => !q || r.d.name.toLowerCase().indexOf(q) >= 0 || r.d.counties.join(" ").toLowerCase().indexOf(q) >= 0);
    return '<div class="rowBtns"><button class="btn" data-act="simRun"' + (n ? "" : " disabled") + ">Run the simulation: " + (n === 1 ? U.esc(simMembers()[0].name) : n === GROUPABLE.length ? "all " + n + " districts" : n + " districts") + ' &rarr;</button></div>' +
      '<div class="pickBar"><input id="simSearch" type="search" placeholder="Search for a district or county" value="' + U.esc(state.simQuery || "") + '"><button class="btn ghost small" data-act="simAll">Tick all</button><button class="btn ghost small" data-act="simNone">Clear</button></div>' +
      "<div class=\"scroll\" style=\"max-height:330px\"><table class=\"t replay\"><tr><th></th><th>District</th><th class=\"r\">Crop loss if nothing is done</th><th class=\"r\">Modelled saving from sealing early</th></tr>" +
      rows.map((r) => r.alone
        ? '<tr class="go" data-act="district" data-i="' + U.esc(r.i) + '"><td>&rarr;</td><td>' + U.esc(r.d.name) + ' <span class="muted">opens on its own (different reservoir)</span></td><td class="r">' + rangeCell(r.loss, money, "future") + '</td><td class="r">' + rangeCell(r.saved, money, "future") + "</td></tr>"
        : '<tr class="go" data-act="simPick" data-i="' + U.esc(r.i) + '"><td><input type="checkbox" tabindex="-1"' + (state.simSel.has(r.i) ? " checked" : "") + "></td><td>" + U.esc(r.d.name) + ' <span class="muted">' + U.esc(r.d.counties.join(", ")) + '</span></td><td class="r">' + rangeCell(r.loss, money, "future") + '</td><td class="r">' + rangeCell(r.saved, money, "future") + "</td></tr>").join("") +
      (rows.length ? "" : '<tr><td colspan="4" class="muted">No district matches.</td></tr>') +
      '</table></div><p class="fn">Modelled, not measured. Five years, 100 possible futures for each district on its own: the middle future, with the range 8 in 10 futures fall in beneath it. Ticked districts run together.</p>';
  }

  /* ---------- What the Simulation step shows ----------
     Every modelled figure on this step is a range: the middle, with the low and high that 8 in 10
     runs fall between. Nothing here is a single dollar or water figure, and nothing is measured. */
  const DRAWS = 300;                                         // draws of the canal unknowns in the replay, and futures in the stress test
  const TAG_MODELLED = ' <span class="tag assumption">modelled, not measured</span>';
  const pctOf = (v) => Math.round(v * 100) + "%";
  /* Which of the two regimes the runs are in (see samplePhysics in sim/engine.js), in a sentence. */
  const regimeSentence = (calibrated) => (calibrated
    ? "Leak rates are calibrated to each district's published loss, so the share of that loss that is seepage is drawn too."
    : "Leak rates are the published rates for each soil; calibrating them to district losses did not predict a hidden district better than canal length alone.");
  /* What the held-out test of the leak model found. Shown wherever volumes and dollars are. */
  const heldOutNote = () => '<p class="note">' + U.esc(window.HGLogic.HELD_OUT_SENTENCE) + "</p>";
  /* The unknowns every run draws, with their ranges. Shown next to the sliders. */
  function unknownsHtml(P, calibrated) {
    const D = E.DEFAULTS, item = (text, tag, label) => "<li>" + text + ' <span class="tag ' + tag + '">' + label + "</span></li>";
    const ft = (v) => U.num(v, v % 1 ? 1 : 0);
    return '<p class="fn"><b>Drawn afresh in every run, not set by a slider</b></p><ul class="plain">' +
      item("Share of seepage the sealant stops: " + pctOf(D.cutLow.value) + " to " + pctOf(D.cutHigh.value) + ". This used to be a slider; a slider would now do nothing, so it is gone.", "published", "published range") +
      item("Wetted canal width: " + ft(P.widthFt * D.widthMultLow.value) + " to " + ft(P.widthFt * D.widthMultHigh.value) + " ft (" + D.widthMultLow.value + " to " + D.widthMultHigh.value + " times the width set above). No width is measured." +
        (calibrated ? " Once calibrated, it changes the sealant bill only." : ""), "assumption", "our assumption") +
      (calibrated
        ? item("Share of a district's canal loss that is seepage: " + pctOf(D.seepShareLow.value) + " to " + pctOf(D.seepShareHigh.value) + ".", "assumption", "our assumption")
        : item("Share of canal length already lined: " + pctOf(D.linedShareLow.value) + " to " + pctOf(D.linedShareHigh.value) + ", most likely " + pctOf(D.linedShareMode.value) + ". No public record says which canals are lined.", "assumption", "our assumption")) +
      "</ul><p class=\"fn\">" + regimeSentence(calibrated) + " Where a figure is given with each unknown at the middle of its range, these are the unknowns meant.</p>";
  }

  /* The replay across the draws is the slow part of this step, so it is kept until its inputs change. */
  const bandsCache = {};
  function bandsFor(name, scope, over) {
    const key = JSON.stringify([scope.ids, scope.firstYear, scope.lastYear, over, L.physicsOptions()]);
    if (!bandsCache[name] || bandsCache[name].key !== key) {
      bandsCache[name] = { key, result: window.HGLogic.replayBands(scope, over, { draws: DRAWS, physicsOptions: L.physicsOptions() }) };
    }
    return bandsCache[name].result;
  }
  /* A table of ranges for the five policies, the sentence written from it, and the two count lines. */
  function bandsBlock(result, withScoredTest) {
    const lines = window.HGLogic.replayBandsLines(result), shared = window.HGLogic.sharedForecastSentence(result);
    return window.HGLogic.replayBandsTable(result) +
      '<p class="fn">Each figure is the middle of ' + U.esc(result.draws) + " draws of what is not known about the canals; under it, the range 8 in 10 draws fall in. Sealant spent, water kept (in thousands of acre-feet), crop loss and saving against doing nothing are all modelled.</p>" +
      '<p class="rec">' + U.esc(window.HGLogic.replayBandsSentence(result).text) + "</p>" +
      (withScoredTest ? '<p class="rec">' + U.esc(window.HGLogic.SCORED_TEST_SENTENCE) + "</p>" : "") +
      (shared ? '<p class="fn">' + U.esc(shared) + "</p>" : "") +
      '<p class="fn">' + U.esc(lines.worse) + "<br>" + U.esc(lines.overBudget) + "</p>";
  }
  /*
    The replay that leads the Simulation step: the real years that have forward-chained forecasts,
    run through five policies (js/logic.js does the sums with the engine), once for every draw of
    the canal unknowns.
  */
  function replayHtml(over) {
    const scope = L.replayScope(simMembers());
    if (!scope) return "";                                   // the data holds no year with forecasts
    const result = bandsFor("replay", scope, over), P = E.makeParams(over);
    return '<section class="replay"><h3>Replay of the real record, ' + U.esc(result.firstYear) + " to " + U.esc(result.lastYear) + TAG_MODELLED + "</h3>" +
      '<p class="fn">What each policy would have done in the years that really happened: the real weekly drought record, the real reservoir levels, and each year\'s forecast as it was really made, by a model trained only on earlier years. ' +
      "The weather is fixed, so the ranges come only from what is not known about the canals: how well the sealant works, how wide the canals are and how much of them is already lined. " + regimeSentence(result.calibrated) + "</p>" +
      heldOutNote() +
      bandsBlock(result, true) +
      '<p class="fn">Modelled, not measured: none of these savings happened. Modelled saving is the crop loss avoided minus the sealant spent, against doing nothing. ' +
      "Water kept counts every week the sealant was working; it lowers the crop loss only in weeks with a shortage. " +
      "Sealant budget (an input) " + U.usd(over.budget) + " each round, up to " + U.esc(P.applications) + (P.applications === 1 ? " round" : " rounds") + " in a year a policy seals.</p></section>";
  }

  function renderSimResult() {
    if (!simMembers().length) {                                // nothing ticked: show the list only
      $("simLead").innerHTML = districtTable(state.overrides, hitRates(), []); $("simResult").innerHTML = ""; $("simNotes").innerHTML = ""; $("shockRow").innerHTML = ""; $("simUnknowns").innerHTML = "";
      return;
    }
    const scope = simScope(), over = Object.assign({}, state.overrides, { budget: state.budget }), P = E.makeParams(over);
    $("simBudgetOut").textContent = U.usd(state.budget);
    const plan = E.fundCanals(scope.canals, state.budget, P);
    const who = scope.members > 1 ? scope.members + " districts on the " + scope.system + " system" : "this district";
    const which = caseOf(state.simCase), hit = hitRates(), on = SHOCKS.filter((s) => state.shocks[s.key]);
    const showCheck = state.simStep === 3 && state.simCase === "check";
    const physicsOptions = L.physicsOptions(), central = E.centralPhysics(physicsOptions);   // central: each canal unknown at the middle of its range
    $("simUnknowns").innerHTML = unknownsHtml(P, central.calibrated);
    // The real 2020 to 2025 record, with the forecasts the frozen model made for those years.
    const test = Object.assign({}, scope, { weeks: scope.weeks.filter((w) => w.year >= 2020 && w.year <= 2025), firstYear: 2020, lastYear: 2025 });
    let run = null, html = "", pair = null, note = "";

    if (!showCheck) {
      const res = reservoirFor(district());
      const futures = (policies, budget, draws, withFixed) => E.fromToday(scope, policies, Object.assign({}, over, { budget }), {
        startDate: TODAY, pctNow: res.pct == null ? 50 : res.pct, pNow: scope.pNow, years: 5, draws, seed: 11,
        cutoffYear: 2020, recall: hit.recall, falseAlarm: hit.falseAlarm,
        shocks: on.filter((s) => s.shock).map((s) => s.shock), secondDryYear: on.some((s) => s.secondDryYear),
        physics: true, physicsOptions, withFixed });
      run = futures(POLICIES.map((pol) => ({ trigger: pol.trigger })), state.budget, DRAWS, true);
      // What each policy gains over doing nothing, future by future: with the canal unknowns drawn, and with them at the middle.
      const gain = (set, i) => band(set[i].draws.map((t, k) => set[0].draws[k].cost - t.cost));
      const act = run.policies[2], base = run.policies[0];
      const kept = band(act.draws.map((t, k) => base.draws[k].loss - t.loss));
      const mult = U.PUBLISHED.worstCaseOutput / U.PUBLISHED.worstCaseRevenue;      // total economic output per $1 of crop revenue (Texas A&M)
      // The same question at other budgets (fewer futures, to stay quick): does more sealing still pay?
      const top = maxBudget(), levels = [0, 0.1, 0.25, 0.5, 0.75, 1].map((f) => Math.round(top * f));
      const curve = levels.map((b) => {
        if (b === 0) return { low: 0, mid: 0, high: 0 };
        const r = futures([{ trigger: "never" }, { trigger: "forecast" }], b, 120, false);
        return gain(r.policies, 1);
      });
      const curveHtml = "<h3>Modelled net saving by budget</h3><div class=\"chart\">" +
        lineChart([{ name: "Five-year modelled net saving: middle future (line) and 8 in 10 futures (shaded)", color: U.TIER_COLOR.Low, values: curve.map((c) => c.mid) }], levels.map((b) => money(b)), money,
                  { low: curve.map((c) => c.low), high: curve.map((c) => c.high), color: U.TIER_COLOR.Low }) + "</div>" +
        (state.budget < top ? '<div class="rowBtns"><button class="btn small" data-act="fullBudget">Fund every rankable canal</button></div>' : "");
      const cell = (b) => '<td class="r">' + rangeCell(b, money, "future") + "</td>";
      const policyRows = POLICIES.map((pol, i) => "<tr><td>" + U.esc(pol.name) + "</td>" + cell(run.policies[i].summary.cost) +
        (i ? cell(gain(run.policies, i)) + cell(gain(run.fixedPhysics.policies, i)) + '<td class="r">' + U.esc(run.policies[i].losesToNothing) + " of " + DRAWS + "</td>"
           : '<td class="r"></td><td class="r"></td><td class="r"></td>') + "</tr>").join("");
      simFacts = {
        start: U.niceDate(TODAY), system: scope.system, pct: res.pct, live: res.live, pNow: scope.pNow, library: run.libraryYears, dry: run.dryYears,
        recall: hit.recall, falseAlarm: hit.falseAlarm, shocks: on.map((x) => x.label + " (" + x.note + ")"),
        cases: state.simStep > 1 ? CASES.filter((c) => c.key !== "check").map((c) => c.name + ": " + run.cases[c.key].sourceYears.join(", ")) : [], share: scope.share,
        outsideValley: scope.outsideValley, who, P,
      };
      html = '<p class="fn">' + DRAWS + " possible futures to " + (Number(TODAY.slice(0, 4)) + 5) + ", built from real past years and started from today's reservoir level. Each future also draws what is not known about the canals. " +
        "Each figure is the middle future, with the range 8 in 10 futures fall in beneath it.</p>" +
        '<div class="tableWrap"><table class="t replay"><tr><th>Policy</th><th class="r">Total cost</th><th class="r">Saving vs nothing</th><th class="r">Same, each unknown at the middle</th><th class="r">Worse than nothing in</th></tr>' + policyRows + "</table></div>" +
        '<p class="fn">Total cost is lost crops plus sealant; all of it is modelled. The first saving column includes what is not known about the canals. The second holds each canal unknown at the middle of its range, so its spread is the weather alone. ' +
        "The difference between the two is what we do not know about the canals, as opposed to the weather.</p>" +
        "<ul class=\"plain\">" +
        "<li>Modelled crop loss avoided by sealing when the forecast warns: " + rangeText(kept, money, "future") + ".</li>" +
        "<li>Modelled value of that to the wider economy (jobs, suppliers, processing; Texas A&amp;M, " + mult.toFixed(1) + " times crop revenue): " + rangeText(kept, (v) => money(v * mult), "future") + ".</li>" +
        "<li>Sealant spent when the forecast warns: " + rangeText(act.summary.spend, money, "future") + ".</li>" +
        "<li>Sealing when the forecast warns ended worse than doing nothing in " + U.esc(act.losesToNothing) + " of " + DRAWS + " futures (wet years: the sealant was not needed); with each unknown at the middle of its range, in " + U.esc(run.fixedPhysics.policies[2].losesToNothing) + ".</li>" +
        "<li>" + (act.overBudget ? "A sealing round cost more than the budget in " + U.esc(act.overBudget) + " of " + DRAWS + " futures: the plan is made at the assumed canal width, and in those futures the canals were wider."
                                 : "In none of the " + DRAWS + " futures did a sealing round cost more than the budget.") + "</li></ul>" +
        more("Modelled net saving by budget", curveHtml) +
        more("Reservoir storage in the " + DRAWS + " futures", '<div class="chart">' +
          lineChart([{ name: "Middle future", color: U.TIER_COLOR.Low, values: run.fan.map((w) => w.mid) },
                     { name: "Full supply above", color: U.LEVEL_COLOR["Unknown soil"], values: run.fan.map(() => P.fullAt), dash: true },
                     { name: "No supply below", color: U.TIER_COLOR.Warning, values: run.fan.map(() => P.zeroAt), dash: true }],
                    run.fan.map((w) => w.date.slice(0, 4)), (v) => Math.round(v) + "%", { low: run.fan.map((w) => w.low), high: run.fan.map((w) => w.high), color: U.TIER_COLOR.Low }) + "</div>");
      if (state.simStep === 3) {
        pair = [run.cases[which.key].sampleFixed[0], run.cases[which.key].sampleFixed[2]];
        note = "Weather borrowed from " + run.cases[which.key].sourceYears.join(", ") + ", started from today's reservoir level";
      }
    } else {
      // The same five policies on 2020 to 2025, across the same draws of the canal unknowns.
      const result = bandsFor("check", test, over), t = FROZEN && FROZEN.test.preSeason;
      const fixed = Object.assign({}, test, { physics: central });
      pair = [E.simulate(fixed, { trigger: "never" }, over), E.simulate(fixed, { trigger: "forecast" }, over)];
      note = "The real record: real drought, real reservoir levels, the forecasts the frozen model made";
      html = '<p class="fn">Real drought and real reservoir levels, 2020 to 2025, with the forecasts made by the model frozen at the end of 2019, which never saw these years. ' +
        "The ranges come from what is not known about the canals.</p>" +
        bandsBlock(result) +
        (t ? "<h3>Forecast accuracy, January to March warnings</h3><div class=\"scroll\" style=\"max-height:none\"><table class=\"t\"><tr><th>Rule</th><th class=\"r\">Drought seasons caught</th><th class=\"r\">Warnings that were right</th></tr>" +
          "<tr><td><b>Our forecast</b> (trained before 2020)</td><td class=\"r\">" + U.esc(t.forecast.caught) + " of " + U.esc(t.forecast.droughtSeasons) + " (" + Math.round(t.forecast.recall * 100) + "%)</td><td class=\"r\">" + Math.round(t.forecast.precision * 100) + "%</td></tr>" +
          "<tr><td>Simple rule: already in moderate drought</td><td class=\"r\">" + U.esc(t.d1Rule.caught) + " of " + U.esc(t.d1Rule.droughtSeasons) + " (" + Math.round(t.d1Rule.recall * 100) + "%)</td><td class=\"r\">" + Math.round(t.d1Rule.precision * 100) + "%</td></tr></table></div>" +
          '<p class="fn">' + U.esc(t.forecast.rows) + " county-months, 14 Texas river counties, " + U.niceDate(FROZEN.test.from) + " to " + U.niceDate(FROZEN.test.to) + ". The two are close.</p>" : "") +
        '<p class="fn">False alarms: in ' + U.esc(pair[1].totals.falseAlarms) + " of the " + U.esc(pair[1].totals.yearsActed) + " years the forecast policy sealed, there was no shortage for the kept water to fill.</p>";
    }

    // What the stage shows, and what leads the panel, for the current sub-step.
    let lead = "", watching = "";
    if (state.simStep === 1) lead = districtTable(over, hit, on);
    else if (state.simStep === 3) {
      loadTwin(pair[0], pair[1], scope, P, plan, which, note);
      simFacts = Object.assign(simFacts || {}, { watching: which.name + ": " + note });
      // The picture is one future. It carries no figures of its own: the ranges are in the tables.
      watching = '<p class="fn">The picture shows one case, ' + U.esc(which.name.toLowerCase()) + " (" + U.esc(which.note) + "), with each canal unknown held at the middle of its range. " + U.esc(note) + ".</p>" +
        more("How to read the picture", '<dl class="key">' +
          "<dt>Reservoir</dt><dd>The lakes on the river that feed the canals. The bar at the top shows how full they are. Below " + P.fullAt + "% full, farms get less water than they asked for.</dd>" +
          "<dt>Green and brown</dt><dd>Each district shape fills with green for the share of water that reached its farms that week. Brown is water that did not arrive.</dd>" +
          "<dt>Red and white lines</dt><dd>Canals. Red canals are unsealed and leak into the soil. White canals have been sealed.</dd>" +
          "<dt>Scenario</dt><dd>" + which.name + ": " + which.note + ".</dd></dl>");
    }
    // The replay of real years leads the results. The random futures follow as a stress test.
    $("simLead").innerHTML = lead;
    $("shockRow").innerHTML = showCheck ? "" : '<div class="shocks"><span>What if things get worse or better? (our assumptions; they change the stress test, not the replay)</span>' + SHOCKS.map((s) => '<button class="sbtn ' + (state.shocks[s.key] ? "on" : "") + '" data-shock="' + s.key + '" title="' + s.note + '">' + s.label + "</button>").join("") + "</div>";
    $("simResult").innerHTML = replayHtml(over) +
      "<h3>" + (showCheck ? U.esc(which.name) + ", 2020 to 2025" : "Stress test: random futures") + TAG_MODELLED + "</h3>" + watching + html;

    $("simNotes").innerHTML = '<div class="rowBtns"><button class="btn ghost" data-act="go" data-step="sources">Data and sources &rarr;</button></div>';
  }

  /* ---------- Step 4: Data and sources ----------
     Everything a researcher needs to check the numbers: each dataset, what it was used for,
     and where it came from. The simulation's own inputs are listed last. */
  let simFacts = null;
  function renderSources() {
    renderSim();                                           // runs the simulation once so its inputs can be listed
    const F = simFacts || {}, a = HG.plan.assumptions, t = FROZEN && FROZEN.test.preSeason, P = params();
    const link = (text, url) => anchor(text, url, false);            // text and address are both escaped; a bad address shows text only
    const table = (rows) => '<table class="t src"><tr><th>Used for</th><th>Data</th><th>Source</th></tr>' + rows.map((r) => "<tr><td>" + r[0] + "</td><td>" + r[1] + "</td><td>" + r[2] + "</td></tr>").join("") + "</table>";
    const tag = (k) => ' <span class="tag ' + k + '">' + k + "</span>";
    $("view").innerHTML =
      "<h2>Data and sources</h2><div class=\"sub\">Every dataset, what it is used for and where it comes from. Data as of " + U.niceDate(HG.week) + ".</div>" +
      heldOutNote() +
      "<h3>1. Drought forecast model</h3>" + table([
        ["Drought class each week, each county (the model's main input and its answer)", "U.S. Drought Monitor, weekly, 2000 on", link("droughtmonitor.unl.edu", "https://droughtmonitor.unl.edu/")],
        ["El Ni&ntilde;o signal", "Oceanic Ni&ntilde;o Index, monthly", link("NOAA Climate Prediction Center", "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt")],
        ["Model", "Random forest, 80 trees. Predicts a drought season (8 straight weeks at D2 or worse) in the next 26 weeks. Warning line " + U.pct(HG.threshold) + ".", "Our pipeline" + tag("pipeline")],
        ["Frozen copy used by the simulation", FROZEN ? U.num(FROZEN.trainedOn.rows) + " county-months, " + U.niceDate(FROZEN.trainedOn.from) + " to " + U.niceDate(FROZEN.trainedOn.to) + ". Nothing after 2019 is learned from." : "n/a", "Our pipeline" + tag("pipeline")],
      ]) +
      (t ? '<table class="t"><tr><th>Test, ' + U.niceDate(FROZEN.test.from) + " to " + U.niceDate(FROZEN.test.to) + '</th><th class="r">Seasons caught</th><th class="r">Warnings right</th><th class="r">False alarms</th></tr>' +
        [["Forecast", t.forecast], ["Rule: already in D1", t.d1Rule]].map(([n, x]) => "<tr><td>" + n + '</td><td class="r">' + U.esc(x.caught) + " / " + U.esc(x.droughtSeasons) + " (" + Math.round(x.recall * 100) + '%)</td><td class="r">' + Math.round(x.precision * 100) + '%</td><td class="r">' + U.esc(x.falseAlarms) + "</td></tr>").join("") +
        '</table><p class="fn">January to March warnings, ' + U.esc(t.forecast.rows) + " county-months in the 14 Texas river counties. The forecast matches the simple rule; it does not clearly beat it.</p>" : "") +
      "<h3>2. Canals, soils and districts</h3>" + table([
        ["Canal lines", "National Hydrography Dataset, Canal/Ditch features", link("U.S. Geological Survey", "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/6")],
        ["Extra canals, names, piped stretches", HG.osm ? U.num(HG.osm.added) + " segments, " + U.num(HG.osm.addedKm) + " km" : "n/a", link("OpenStreetMap contributors (ODbL)", "https://www.openstreetmap.org/copyright")],
        ["Soil under each canal", "SSURGO soil survey", link("USDA NRCS Soil Data Access", "https://sdmdataaccess.sc.egov.usda.gov/")],
        ["District boundaries", HG.districts.length + " active districts", link("TCEQ Water Districts", "https://gisweb.tceq.texas.gov/arcgis/rest/services/iwud/WaterDistricts_PRD/MapServer")],
      ]) +
      "<h3>3. Water leaking from canals</h3>" + table([
        ["Leak rate by soil, unlined canals", Object.keys(HG.seepage).filter((k) => !/sand$/i.test(k) || k === "Sand").map((k) => U.esc(k + " " + HG.seepage[k])).join(" · ") + " gallons per sq ft per day", link("Fipps, Texas A&M, 1998, Tables 6 to 8", "https://gfipps.tamu.edu/files/2019/12/RGV-Potential-Water-Savings.pdf") + " (Table 7 quotes the Texas Board of Water Engineers, 1946)"],
        ["Canal size", U.esc(a.wetted_width_ft) + " ft wetted width for every canal", "Ours" + tag("assumption")],
        ["Units", "Water agencies count in acre-feet. One acre-foot is 325,851 gallons, about half an Olympic pool. The platform shows gallons.", "Conversion"],
        ["Scale check", "Published potential saving in 28 Valley districts: 54,000 to 223,000 acre-feet a year. The simulation's own water figures are ranges, on the Simulation step.", link("Fipps, 1998", "https://gfipps.tamu.edu/files/2019/12/RGV-Potential-Water-Savings.pdf")],
      ]) +
      '<p class="fn">Leakage counts only weeks when water is released, and never more than was released. It assumes every ranked canal is unlined, because no source records lining. Treat it as an upper estimate.</p>' +
      "<h3>4. Sealant</h3>" + table([
        ["Price", "$" + U.esc(a.sealant_usd_per_sqft) + " per sq ft, materials only", link("U.S. Bureau of Reclamation", "https://www.usbr.gov/research/projects/detail.cfm?id=845")],
        ["Share of leakage stopped", Math.round(a.sealant_cut_low * 100) + "% to " + Math.round(a.sealant_cut_high * 100) + "% in field trials; every simulation run draws a value from this range", "Desert Research Institute field trials"],
        ["How long it lasts", "About " + U.esc(a.days_one_application_lasts) + " days; " + P.applications + " applications cover a season", "Lund et al., 2021"],
        ["Crew speed", P.kmPerCrewDay + " km per crew per day, " + P.crews + " crews", "Ours" + tag("assumption")],
      ]) +
      "<h3>5. Money</h3>" + table([
        ["Crop revenue lost in a year with no irrigation water", U.usd(U.PUBLISHED.worstCaseRevenue) + "; total output " + U.usd(U.PUBLISHED.worstCaseOutput) + "; " + U.num(U.PUBLISHED.worstCaseJobs) + " jobs", link("Texas A&M AgriLife, 2023", U.PUBLISHED.worstCaseUrl)],
        ["Full irrigation demand", U.num(U.PUBLISHED.valleyIrrigationAf) + " acre-feet a year (2011 use)", link("Region M Water Plan, Table 2-8", U.PUBLISHED.valleyIrrigationUrl)],
        ["Value of an acre-foot in a shortage", "$" + U.num(U.USD_PER_AF) + ": the two figures above, divided", "Ours" + tag("assumption")],
        ["A district's share", "By canal length" + (F.share ? "; " + F.who + " holds " + Math.round(F.share * 100) + "% of Valley canal length" : ""), "Ours" + tag("assumption")],
      ]) +
      "<h3>6. Reservoirs</h3>" + table([
        ["Storage, daily", "Amistad, Falcon, Elephant Butte", link("Texas Water Development Board", "https://www.waterdatafortexas.org/reservoirs/statewide")],
        ["Water released to farms", "Full supply at " + P.fullAt + "% storage, none at " + P.zeroAt + "%, a straight line between", "Ours" + tag("assumption") + "; the real rule is " + link(U.PUBLISHED.allocationRule.text, U.PUBLISHED.allocationRule.url)],
        ["Drought declaration", "8 straight weeks at D2", link(U.PUBLISHED.disasterRule.text, U.PUBLISHED.disasterRule.url)],
      ]) +
      "<h3>7. This simulation run</h3>" + (F.start ? table([
        ["Start", F.start + "; " + F.system + " at " + (finiteOrNull(F.pct) == null ? "n/a" : F.pct + "%") + " (" + (F.live ? "live" : "saved") + " reading)", "Texas Water Development Board"],
        ["Chance the first season is dry", U.pct(F.pNow), "Frozen forecast model, this week's data"],
        ["Weather the futures are built from", F.library.length + " real years, " + F.library[0] + " to " + F.library[F.library.length - 1] + "; " + F.dry.length + " had a drought season (" + F.dry.join(", ") + ")", "U.S. Drought Monitor, Texas Water Development Board"],
        ["Forecast accuracy inside the simulation", "Warns before " + Math.round(F.recall * 100) + "% of dry seasons and " + Math.round(F.falseAlarm * 100) + "% of wet ones. A wrong warning costs the sealant for that year and keeps no water that was needed.", "Test above"],
        ["Futures", "300 draws, fixed seed, so every visit shows the same result", "Ours"],
      ].concat((F.cases || []).map((c) => ["Scenario weather", c, "Real years, replayed from today's storage"]))
       .concat(F.shocks && F.shocks.length ? [["Stress tests switched on", F.shocks.join("; "), "Ours" + tag("assumption")]] : [])) : "") +
      (F.outsideValley ? '<p class="fn warn">The crop-loss figure covers Cameron, Hidalgo, Starr and Willacy counties. Using its value per acre-foot here is our extrapolation.</p>' : "") +
      "<h3>Limits</h3><ul class=\"plain\"><li>Saved water counts only in a shortage. Above " + P.fullAt + "% storage, sealing earns nothing.</li><li>The sealant has not been field-tested on the Rio Grande. Prices are materials only.</li>" +
      "<li>Which field squares are dry in the picture is illustration; the share is the model's.</li><li>" + U.esc(HG.plan.note) + "</li></ul>";
  }

  /* ---------- Putting it together ---------- */
  function refresh(refit) {
    document.querySelectorAll("#stepper button").forEach((b) => b.classList.toggle("on", b.dataset.step === state.step));
    const sim = state.step === "sim";
    if (sim && !district() && !simMembers().length) state.simStep = 1;         // nothing ticked yet: stay on the list
    $("stage").classList.toggle("flow", sim);                                   // chips and prompt over the stage
    $("stage").classList.toggle("sim", sim && state.simStep === 3);             // the twin picture instead of the map
    if (sim) simChrome();
    $("scopeBtn").innerHTML = "<small>" + (district() ? "District" : "View") + "</small>" + U.esc(scopeName()) + " &#9662;";
    $("viewScope").textContent = district() ? "My district" : "All of Texas";
    ({ risk: renderRisk, budget: renderBudget, sim: renderSim, sources: renderSources })[state.step]();
    syncMap();
    $("view").scrollTop = 0;
    if (sim && state.simStep === 3) twin.play(); else twin.pause();
    // On the district list, open the map on the Lower Valley, where most districts are, close
    // enough to tap one. The buttons above the map jump to El Paso and Eagle Pass.
    if (sim && !district() && state.simStep === 1 && !map.isScanning()) map.flyTo("valley");
    else if (refit && !map.isScanning()) map.fitScope();
  }
  function setScope(scope, noScan) {
    state.scope = scope; state.county = null; state.canal = null; state.severity = null;
    state.simStep = scope === STATE ? 1 : 3; state.simCase = "likely"; state.simQuery = "";       // a district goes straight to the average case
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
    if (act === "simPick") { const i = Number(t.dataset.i); simMembers(); state.simSel.has(i) ? state.simSel.delete(i) : state.simSel.add(i); renderSimResult(); simChrome(); }
    if (act === "simAll") { state.simSel = new Set(GROUPABLE); renderSimResult(); simChrome(); }
    if (act === "simNone") { state.simSel = new Set(); renderSimResult(); simChrome(); }
    if (act === "simRun") { state.simCase = "likely"; state.simStep = 3; refresh(false); }
    if (act === "fullBudget") { state.budget = maxBudget(); renderSim(); }
    if (act === "canal") { state.canal = Number(t.dataset.id); map.flyToCanal(state.canal); refresh(false); }
  });
  $("lightbox").onclick = () => $("lightbox").classList.remove("on");
  $("view").addEventListener("click", (e) => {
    const sev = e.target.closest("#sev button"), shock = e.target.closest("[data-shock]");
    if (sev) { state.severity = sev.dataset.p === "" ? null : Number(sev.dataset.p); renderBudget(); }
    if (shock) { state.shocks[shock.dataset.shock] = !state.shocks[shock.dataset.shock]; renderSimResult(); if (state.simStep === 3) twin.play(); }
  });
  /* On the Simulation step a slider redraws the results a moment after it stops moving, not on
     every step of the drag: the runs behind them take a noticeable fraction of a second. */
  let simTimer = null;
  function laterSim() {
    clearTimeout(simTimer);
    simTimer = setTimeout(() => { if (state.step !== "sim" || !$("simResult")) return; renderSimResult(); if (state.simStep === 3) twin.play(); }, SLIDER_PAUSE_MS);
  }
  const SLIDER_PAUSE_MS = 250;
  $("view").addEventListener("input", (e) => {
    if (e.target.id === "budget") { state.budget = Number(e.target.value); renderBudgetResult(); }
    if (e.target.id === "simSearch") {                          // filter the list as you type, keeping the cursor in the box
      state.simQuery = e.target.value; renderSimResult();
      const box = $("simSearch"); box.focus(); box.setSelectionRange(box.value.length, box.value.length);
    }
    if (e.target.id === "simBudget") { state.budget = Number(e.target.value); $("simBudgetOut").textContent = U.usd(state.budget); laterSim(); }
    if (e.target.dataset.param) {
      const k = e.target.dataset.param, row = SLIDERS.find((s) => s[0] === k);
      state.overrides[k] = Number(e.target.value);
      if (k === "fullAt" || k === "zeroAt") {                   // keep "none" below "all"
        const p = params();
        if (p.zeroAt >= p.fullAt) state.overrides.zeroAt = p.fullAt - 1;
      }
      $("o_" + k).textContent = row[4](state.overrides[k]);
      if (state.step === "sim") laterSim(); else renderBudgetResult();
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
      .map(({ d, i }) => '<button data-i="' + U.esc(i) + '"><span><b>' + U.esc(d.name) + "</b><small>" + U.esc(d.counties.join(", ")) + " · " + U.num(d.canalKm) + " km of canals</small></span>" + chip(d.risk) + "</button>").join("") ||
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
    // "Live" only if a live reading is really in use. If every one was missing or rejected, the
    // page is showing the readings saved by the last pipeline refresh, dated the forecast week.
    const live = ["Amistad-Falcon", "Elephant Butte"].some((name) => liveReading(name));
    $("live").classList.toggle("saved", !live);
    $("liveText").textContent = (live ? "Reservoirs live · " : "Reservoirs: saved reading of " + U.niceDate(HG.week) + " · ") + "forecast week of " + U.niceDate(HG.week);
  }
  showLive();
  fetch("api/live").then((r) => (r.ok ? r.json() : Promise.reject())).then((data) => {
    if (data && data.systems) { state.live = data; showLive(); if (state.scope != null) { if (state.step === "risk") renderRisk(); if (state.step === "sim") renderSimResult(); syncMap(); } }
  }).catch(() => { /* keep the saved reading */ });

  /* ---------- Start: use the link, then the remembered choice, else ask ---------- */
  // There is no sign-in, so every visit starts by asking who you are and which district.
  // A link that names a scope (#state or #d=District name) skips the question.
  const byName = (name) => HG.districts.findIndex((d) => d.name === name);
  const hash = window.HGLogic.safeDecode(location.hash.slice(1));   // a malformed link must not stop the page from starting
  if (location.search.indexOf("step=") >= 0) state.step = location.search.split("step=")[1].split("&")[0];   // for links straight to a step
  if (hash === "state") setScope(STATE);
  else if (hash.indexOf("d=") === 0 && byName(hash.slice(2)) >= 0) setScope(byName(hash.slice(2)));
  else { state.scope = STATE; state.budget = defaultBudget(); refresh(true); openChooser(); }
})();
