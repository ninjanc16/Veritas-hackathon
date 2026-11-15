/*
  platform.js: the platform (app.html).

  HOW IT IS ORGANISED
    state      one object holding every choice the user has made (scope, step, budget ...)
    the map    a Leaflet map with three layers: counties, districts, canals
    the steps  renderRisk(), renderBudget(), renderSim() each fill the right-hand panel
    refresh()  redraws the map and the current step; called after any change of state

  "Scope" means who is looking: one district (state.scope = its number in HG.districts)
  or the whole state (state.scope = -1).
*/
(function () {
  "use strict";
  const HG = window.HG, SIM = window.HG_SIM, U = window.HGU, E = window.HGEngine;
  const $ = (id) => document.getElementById(id);
  const STATE = -1;
  const ELEPHANT_BUTTE = ["48141", "48229"];           // El Paso and Hudspeth draw on Elephant Butte
  const SEVERITIES = [                                  // the "what if" drought choices in the budget planner
    { p: null, label: "This week's forecast" },
    { p: 0.25, label: "Moderate (25%)" },
    { p: 0.5, label: "Severe (50%)" },
    { p: 0.8, label: "Extreme (80%)" },
  ];

  const state = { scope: null, step: "risk", mapMode: "now", budget: null, severity: null,
                  simMode: "replay", overrides: {}, county: null, live: null };

  /* ---------- Scope helpers ---------- */
  const district = () => (state.scope >= 0 ? HG.districts[state.scope] : null);
  const scopeCanals = () => (state.scope >= 0 ? U.canals.filter((c) => c.district === state.scope)
                                              : U.canals.filter((c) => c.district >= 0));
  const scopeName = () => (district() ? district().name : "State of Texas");
  const usesElephantButte = (d) => d.fips.length > 0 && d.fips.every((f) => ELEPHANT_BUTTE.indexOf(f) >= 0);
  /* The chance of a drought season used by the planner: the "what if" value, or the forecast. */
  function scopeP() {
    if (state.severity != null) return state.severity;
    if (district()) return district().pSeason;
    // State view: the districts' forecasts, weighted by canal km.
    const km = HG.districts.reduce((s, d) => s + d.canalKm, 0);
    return HG.districts.reduce((s, d) => s + d.pSeason * d.canalKm, 0) / km;
  }
  function reservoirFor(d) {
    const name = d && usesElephantButte(d) ? "Elephant Butte" : "Amistad-Falcon";
    const county = HG.river.find((c) => c.reservoir === name);
    let pct = county ? county.reservoirPct : null, date = HG.week, live = false;
    if (state.live && state.live.systems && state.live.systems[name]) {
      pct = state.live.systems[name].pct; date = state.live.systems[name].date; live = true;
    }
    return { name, pct, date, live };
  }

  /* ---------- The map ---------- */
  const map = L.map("map", { zoomControl: true, preferCanvas: true, minZoom: 5, maxZoom: 15 });
  // The background map (roads and town names). It is greyed out in site.css so our colours stand out.
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19, className: "basemap",
  }).addTo(map);
  const canvas = L.canvas({ padding: 0.3, tolerance: 6 });
  const flip = (ring) => ring.map((p) => [p[1], p[0]]);          // our data is [lon, lat]; Leaflet wants [lat, lon]

  const countyShapes = HG.texas.map((c) => {
    const shape = L.polygon(c.rings.map(flip), { renderer: canvas, weight: 0.6, color: "#fff", fillOpacity: 0.7 }).addTo(map);
    shape.bindTooltip(() => c.name + " County: " + (c.dm == null ? "no data" : U.DM_TEXT[c.dm]) +
      (U.riverByFips[c.fips] ? " · 6-month chance " + U.pct(U.riverByFips[c.fips].pSeason) : ""), { sticky: true });
    shape.on("click", () => { state.county = c.fips; if (state.step !== "risk") state.step = "risk"; refresh(false); });
    return { c, shape };
  });
  const districtShapes = HG.districts.map((d, i) => {
    const shape = L.polygon(d.rings.map(flip), { renderer: canvas, weight: 1.5, color: "#0b1f3a", fillOpacity: 0.04, fillColor: "#0b63b5" }).addTo(map);
    shape.bindTooltip(d.name + " · " + d.risk + " (" + U.pct(d.pSeason) + ")", { sticky: true });
    shape.on("click", () => { if (state.scope !== i) setScope(i); });
    return shape;
  });
  const canalGroup = L.layerGroup().addTo(map);
  let canalShapes = [];        // [{ c, shape }] for the canals now on the map

  function canalPopup(c) {
    return "<b>" + U.esc(c.name) + "</b><br>" + U.esc(c.soil || "Unknown soil") + " · leaks " + c.rate + " gal/sq ft/day<br>" +
      "Priority: " + c.level + " · " + U.num(c.km, 2) + " km<br>" +
      (c.rank != null ? "Sealing rank " + c.rank + " of all Texas canals · " + U.usd(c.usd) : "Not in the sealing plan (drain, or soil unknown)") +
      (c.district >= 0 ? "<br>" + U.esc(HG.districts[c.district].name) : "");
  }

  /* Put the scope's canals on the map (only when the scope changes; restyling is separate). */
  function drawCanals() {
    canalGroup.clearLayers();
    const list = state.scope >= 0 ? scopeCanals() : U.canals;
    canalShapes = list.map((c) => {
      const shape = L.polyline(flip(c.line), { renderer: canvas, weight: 2, color: "#888" });
      shape.bindPopup(() => canalPopup(c));
      canalGroup.addLayer(shape);
      return { c, shape };
    });
  }

  /* Colour everything on the map for the current step and choices. */
  function styleMap() {
    const inDistrict = state.scope >= 0, d = district();
    const forecastMode = state.mapMode === "forecast";
    countyShapes.forEach(({ c, shape }) => {
      const river = U.riverByFips[c.fips];
      let fill = c.dm == null ? "#e6ebf1" : U.DM_COLOR[c.dm], opacity = inDistrict ? 0.28 : 0.72;
      if (forecastMode) { fill = river ? U.TIER_COLOR[river.tier] : "#e6ebf1"; opacity = river ? (inDistrict ? 0.3 : 0.75) : 0.25; }
      const picked = state.county === c.fips;
      shape.setStyle({ fillColor: fill, fillOpacity: opacity, color: picked ? "#0b1f3a" : "#fff", weight: picked ? 2.5 : 0.6 });
    });
    districtShapes.forEach((shape, i) => {
      const on = state.scope === i;
      shape.setStyle({ weight: on ? 3 : 1.2, color: on ? "#0b1f3a" : "#3d5673", fillOpacity: on ? 0 : 0.05, dashArray: on ? null : "4 3" });
      if (on) shape.bringToFront();
    });
    const plan = state.step === "risk" ? null : currentPlan();
    const thick = inDistrict ? 1 : 0.6;
    canalShapes.forEach(({ c, shape }) => {
      if (plan) {
        const funded = plan.fundedIds.has(c.id);
        shape.setStyle({ color: funded ? "#0b63b5" : "#a3adba", weight: (funded ? 4 : 1.4) * thick, opacity: funded ? 1 : 0.55 });
        if (funded) shape.bringToFront();
      } else {
        shape.setStyle({ color: U.LEVEL_COLOR[c.level], weight: (c.level === "Inspect first" ? 3.6 : 2) * thick, opacity: 0.9 });
      }
    });
    // Legend
    const key = (color, text, line) => '<span><i class="' + (line ? "lineKey" : "") + '" style="background:' + color + '"></i>' + text + "</span>";
    let html = forecastMode
      ? ["Low", "Watch", "Warning"].map((t) => key(U.TIER_COLOR[t], t)).join("")
      : U.DM_TEXT.map((t, i) => key(U.DM_COLOR[i], t.replace(/ drought$/, ""))).join("");
    html += '<span style="flex-basis:100%;height:2px"></span>';
    html += plan ? key("#0b63b5", "Canal funded by this budget", true) + key("#a3adba", "Not funded", true)
                 : HG.levels.map((l) => key(U.LEVEL_COLOR[l], l, true)).join("");
    $("legendTitle").textContent = forecastMode ? "6-month drought forecast (river counties)" : "Drought this week (U.S. Drought Monitor)";
    $("legend").innerHTML = html;
    $("modeCard").innerHTML = '<button data-mode="now" class="' + (forecastMode ? "" : "on") + '">Drought now</button>' +
      '<button data-mode="forecast" class="' + (forecastMode ? "on" : "") + '">6-month forecast</button>';
  }
  $("modeCard").addEventListener("click", (e) => {
    const mode = e.target.dataset.mode;
    if (mode) { state.mapMode = mode; styleMap(); }
  });

  function fitMap() {
    const d = district();
    if (d) map.fitBounds(districtShapes[state.scope].getBounds(), { padding: [50, 50], maxZoom: 12 });
    else map.fitBounds(L.latLngBounds(countyShapes.map((s) => s.shape.getBounds())), { padding: [10, 10] });
  }

  /* ---------- The budget plan for the current scope, budget and severity ---------- */
  let planCache = null, planKey = "";
  function currentPlan() {
    const k = [state.scope, state.budget, state.severity].join("|");
    if (k !== planKey) { planCache = U.planFor(scopeCanals(), state.budget, state.severity); planKey = k; }
    return planCache;
  }
  function defaultBudget() {
    const all = U.planFor(scopeCanals(), 0, null).costAll;
    if (state.scope === STATE) return Math.min(all, HG.plan.budget_usd);
    return Math.max(100, Math.round(all * 0.25 / 100) * 100);
  }

  /* ---------- Small HTML pieces ---------- */
  const kpi = (label, value, small) => '<div class="kpi"><span>' + label + "</span><b>" + value + "</b>" + (small ? "<small>" + small + "</small>" : "") + "</div>";
  const chip = (tier, text) => '<span class="chip ' + tier + '"><i></i>' + (text || tier) + "</span>";
  function gauge(p) {
    const tier = U.tierFor(p);
    return '<div class="gauge"><i style="width:' + Math.min(100, p * 100) + "%;background:" + U.TIER_COLOR[tier] + '"></i><u style="left:' + HG.threshold * 100 + '%"></u></div>' +
      '<div class="small muted">Warning line at ' + U.pct(HG.threshold) + ". Above it, our test caught " + Math.round(HG.trigger.rules[0].recall * 100) + "% of drought seasons.</div>";
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

  /* ---------- Step 1: Risk profile ---------- */
  function renderRisk() {
    const d = district(), list = scopeCanals(), res = reservoirFor(d);
    let html = "";
    if (state.county && !d) html += countyCard(state.county, true);
    if (d) {
      const act = U.actionFor(d.pSeason);
      const worst = Math.max.apply(null, d.fips.map((f) => U.countyByFips[f].dm || 0));
      const leaky = list.filter((c) => c.rate >= 7.48).reduce((s, c) => s + c.km, 0);
      html += '<button class="back" data-act="state">&larr; All of Texas</button>' +
        "<h2>" + U.esc(d.name) + "</h2><div class=\"sub\">" + U.esc(d.kind) + " · " + d.counties.join(" and ") + " County · " + chip(d.risk) + "</div>" +
        '<div class="card"><div style="display:flex;justify-content:space-between;align-items:baseline"><b>Chance of a drought season in the next 6 months</b><b style="font-family:var(--serif);font-size:1.6rem;color:var(--navy)">' + U.pct(d.pSeason) + "</b></div>" + gauge(d.pSeason) + "</div>" +
        '<div class="card action ' + act.key + '"><span class="small muted">Recommended now</span><b>' + act.title + "</b>" + act.text + "</div>" +
        '<div class="kpis">' +
          kpi("Drought now", U.DM_TEXT[worst].split(" ")[0] === "No" ? "None" : U.DM_TEXT[worst].split(" ")[0], U.DM_TEXT[worst]) +
          kpi(res.name + " reservoirs", res.pct == null ? "n/a" : res.pct + "% full", (res.live ? "Live reading, " : "Saved reading, ") + U.niceDate(res.date)) +
          kpi("Canals in the district", U.num(d.canalKm) + " km", U.num(d.treatableKm) + " km could be sealed") +
          kpi("On leaky soil", U.num(leaky) + " km", "loam or sandier") +
        "</div>" +
        "<h3>Canals by priority</h3><div class=\"card\">" + mixBar(list, (c) => c.level, (k) => U.LEVEL_COLOR[k]) + '<p class="credit" style="margin:8px 0 0">' + U.esc(HG.levelRule) + "</p></div>" +
        "<h3>Canals by soil</h3><div class=\"card\">" + mixBar(list, (c) => c.soil || "Unknown", (k) => { const r = HG.seepage[k]; return r == null ? "#8a94a3" : r >= 7.48 ? "#c9372c" : r >= 2.9 ? "#e0a100" : "#3f8f5f"; }) +
          '<p class="credit" style="margin:8px 0 0">Red soils leak fastest. Seepage rates: ' + U.esc(HG.seepageSource) + ".</p></div>" +
        '<div class="rowBtns"><button class="btn" data-act="go" data-step="budget">Build the budget plan &rarr;</button></div>' +
        issuesFor(d) +
        "<h3>The " + (d.fips.length > 1 ? "counties" : "county") + " it serves</h3>" + d.fips.map((f) => countyCard(f, false)).join("");
    } else {
      const inDrought = HG.texas.filter((c) => c.dm != null && c.dm >= 2).length;
      const warned = HG.river.filter((c) => c.pSeason >= HG.threshold).length;
      const dWarn = HG.districts.filter((x) => x.risk === "Warning").length;
      html += "<h2>State of Texas</h2><div class=\"sub\">Drought across all 254 counties, and the " + HG.districts.length + " irrigation and water districts on the Rio Grande. Week of " + U.niceDate(HG.week) + ".</div>" +
        '<div class="kpis">' +
          kpi("Counties in drought now", inDrought + " of 254", "D1 or worse, U.S. Drought Monitor") +
          kpi("River counties over the warning line", warned + " of 14", "6-month forecast at " + U.pct(HG.threshold) + " or more") +
          kpi(res.name + " reservoirs", res.pct == null ? "n/a" : res.pct + "% full", (res.live ? "Live reading, " : "Saved reading, ") + U.niceDate(res.date)) +
          kpi("Districts at Warning", dWarn + " of " + HG.districts.length, U.num(HG.plan.canal_km_in_districts) + " km of canals in all") +
        "</div>" +
        '<p class="small muted">Click any county on the map for its photos and profile. Click a district, or a row below, to open it.</p>' +
        "<h3>Districts, highest risk first</h3><div class=\"scroll\" style=\"max-height:420px\"><table class=\"t\"><tr><th>District</th><th>Risk</th><th class=\"r\">6-month chance</th><th class=\"r\">Canal km</th></tr>" +
        HG.districts.map((x, i) => ({ x, i })).sort((a, b) => b.x.pSeason - a.x.pSeason).map(({ x, i }) =>
          '<tr class="click" data-act="district" data-i="' + i + '"><td><b>' + U.esc(x.name) + "</b><br><span class=\"muted small\">" + x.counties.join(", ") + "</span></td><td>" + chip(x.risk) + '</td><td class="r">' + U.pct(x.pSeason) + '</td><td class="r">' + U.num(x.canalKm) + "</td></tr>").join("") +
        "</table></div>" +
        '<div class="rowBtns"><button class="btn" data-act="go" data-step="budget">Split a state budget &rarr;</button></div>' +
        issuesFor(null);
    }
    html += '<p class="note" style="margin-top:18px">The forecast comes from a random forest model trained on the drought record since 2000 and re-run on new public data (Drought Monitor weekly, reservoirs daily). In testing it only narrowly beat the simple rule "already in moderate drought", so treat it as months of early warning, not as certainty.</p>';
    $("view").innerHTML = html;
  }

  /* ---------- Step 2: Budget plan ---------- */
  function renderBudget() {
    const d = district(), all = U.planFor(scopeCanals(), 0, null).costAll;
    const max = Math.ceil(all / 100) * 100, stepSize = max > 200000 ? 5000 : max > 20000 ? 500 : 100;
    $("view").innerHTML =
      (d ? '<button class="back" data-act="state">&larr; All of Texas</button>' : "") +
      "<h2>Budget plan</h2><div class=\"sub\">" + U.esc(scopeName()) + ". Set a budget and a drought severity. The list shows exactly which canals to seal, in order.</div>" +
      (all <= 0 ? '<p class="note">No canal in this district is in the sealing plan (its canals are drains or sit on soil with no published seepage rate).</p>' :
      '<div class="card"><div class="field"><label for="budget">Sealing budget <output id="budgetOut"></output></label>' +
      '<input id="budget" type="range" min="0" max="' + max + '" step="' + stepSize + '" value="' + state.budget + '">' +
      '<div class="small muted">Sealing every treatable canal here would cost ' + U.usd(all) + " in sealant materials.</div></div>" +
      '<div class="field"><label>Drought severity to plan for</label><div class="seg" id="sev">' +
      SEVERITIES.map((s) => '<button data-p="' + (s.p == null ? "" : s.p) + '" class="' + (state.severity === s.p ? "on" : "") + '">' + s.label + (s.p == null ? " (" + U.pct(scopeP0()) + ")" : "") + "</button>").join("") +
      "</div></div></div><div id=\"budgetResult\"></div>");
    if (all > 0) renderBudgetResult();
  }
  function scopeP0() { const keep = state.severity; state.severity = null; const p = scopeP(); state.severity = keep; return p; }

  function renderBudgetResult() {
    const plan = currentPlan(), d = district(), p = scopeP(), act = U.actionFor(p), a = HG.plan.assumptions;
    $("budgetOut").textContent = U.usd(state.budget);
    const perAf = (af) => (af > 0 ? "$" + U.num(plan.spent / af, 2) : "n/a");
    let rows;
    if (d) {
      rows = "<h3>Canals in sealing order</h3><div class=\"scroll\"><table class=\"t\"><tr><th>#</th><th>Canal</th><th>Soil</th><th class=\"r\">km</th><th class=\"r\">Cost</th></tr>" +
        plan.ordered.slice(0, 250).map((c, i) => '<tr class="click ' + (plan.fundedIds.has(c.id) ? "" : "off") + '" data-act="canal" data-id="' + c.id + '"><td>' + (i + 1) + "</td><td>" + (plan.fundedIds.has(c.id) ? "<b>" + U.esc(c.name) + "</b>" : U.esc(c.name)) + "</td><td>" + U.esc(c.soil) + '</td><td class="r">' + U.num(c.km, 2) + '</td><td class="r">' + U.usd(c.usd) + "</td></tr>").join("") +
        "</table></div><p class=\"credit\">Bold rows are funded. Click a row to find the canal on the map." + (plan.ordered.length > 250 ? " Showing the first 250 of " + plan.ordered.length + "; the download has every funded canal." : "") + "</p>";
    } else {
      const by = {};
      plan.funded.forEach((c) => { const b = by[c.district] = by[c.district] || { km: 0, usd: 0, n: 0 }; b.km += c.km; b.usd += c.usd; b.n += 1; });
      const order = Object.keys(by).sort((x, y) => by[y].usd - by[x].usd);
      rows = "<h3>Where the money goes</h3><div class=\"scroll\"><table class=\"t\"><tr><th>District</th><th class=\"r\">Canals</th><th class=\"r\">km</th><th class=\"r\">Budget</th></tr>" +
        order.map((i) => '<tr class="click" data-act="district" data-i="' + i + '"><td><b>' + U.esc(HG.districts[i].name) + "</b><div class=\"gauge\" style=\"height:5px;margin:5px 0 0\"><i style=\"background:var(--blue);width:" + (100 * by[i].usd / by[order[0]].usd) + '%"></i></div></td><td class="r">' + by[i].n + '</td><td class="r">' + U.num(by[i].km, 1) + '</td><td class="r">' + U.usd(by[i].usd) + "</td></tr>").join("") +
        "</table></div><p class=\"credit\">" + order.length + " of " + HG.districts.length + " districts receive money. Click a district to open its own canal list.</p>";
    }
    $("budgetResult").innerHTML =
      '<div class="card action ' + act.key + '"><span class="small muted">At a ' + U.pct(p) + " chance of a drought season" + (state.severity != null ? " (your what-if)" : " (the forecast)") + "</span><b>" + act.title + "</b>" + act.text + "</div>" +
      '<div class="kpis">' +
        kpi("Spent", U.usd(plan.spent), "of " + U.usd(state.budget)) +
        kpi("Canal sealed", U.num(plan.km, 1) + " km", plan.funded.length + " canal segments") +
        kpi("Water kept (estimate)", U.num(plan.savedLow) + " to " + U.num(plan.savedHigh), "acre-feet in one " + a.days_one_application_lasts + "-day application") +
        kpi("Sealant cost per acre-foot", perAf(plan.savedHigh) + " to " + perAf(plan.savedLow), "materials only") +
      "</div>" + rows +
      "<h3>How to carry it out</h3><div class=\"card\"><ol class=\"todo\">" +
        "<li><b>Walk the " + plan.funded.length + " funded canal segments (" + U.num(plan.km, 1) + " km).</b> Confirm each is unlined and carries water. Strike any that are already lined: no public data says which are.</li>" +
        "<li><b>Order sealant for about " + U.num(plan.sqft) + " square feet</b> of wetted canal (" + a.wetted_width_ft + " ft assumed width). Materials: " + U.usd(plan.spent) + ". Labour and equipment are extra and not priced here.</li>" +
        "<li><b>Apply before the first irrigation,</b> ideally by early March, starting from the top of the list.</li>" +
        "<li><b>Measure, then repeat.</b> One application lasts about " + a.days_one_application_lasts + " days. Measure flow in and out of a sealed stretch to see what was really saved before paying for a second round.</li>" +
      "</ol></div>" +
      '<div class="rowBtns"><button class="btn" data-act="go" data-step="sim">Simulate this plan &rarr;</button><button class="btn ghost" style="color:var(--blue)" data-act="csv">Download the canal list (CSV)</button></div>' +
      '<p class="note" style="margin-top:16px">Estimate from published figures, not a prediction and not a tested result. ' + U.esc(HG.plan.note) + "</p>";
    styleMap();
  }

  function downloadCsv() {
    const plan = currentPlan();
    const lines = [["order", "canal", "district", "county_fips", "soil", "seepage_gal_sqft_day", "km", "sealant_usd"].join(",")];
    plan.funded.forEach((c, i) => lines.push([i + 1, '"' + c.name.replace(/"/g, '""') + '"', '"' + (c.district >= 0 ? HG.districts[c.district].name : "") + '"', c.fips, '"' + c.soil + '"', c.rate, c.km, c.usd].join(",")));
    const link = U.el("a", { href: URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" })), download: "canal-sealing-plan.csv" });
    document.body.appendChild(link); link.click(); link.remove();
  }

  /* ---------- Step 3: Simulation ---------- */
  const POLICIES = [
    { key: "nothing", trigger: "never", name: "Do nothing", css: "", color: "#8a94a3", blurb: "No canal work. Losses are paid for afterwards." },
    { key: "react", trigger: "declared", name: "Wait for the declaration", css: "react", color: "#e0a100", blurb: "Seal only after 8 straight weeks of severe drought, plus paperwork." },
    { key: "act", trigger: "forecast", name: "Act on the forecast", css: "act", color: "#0b63b5", blurb: "Seal in March whenever the 6-month forecast is over the warning line." },
  ];
  const SLIDERS = [   // the assumptions the user can move: [parameter, min, max, step, how to show it]
    ["cut", 0.28, 0.87, 0.01, (v) => Math.round(v * 100) + "%"],
    ["widthFt", 10, 40, 1, (v) => v + " ft"],
    ["fullAt", 30, 80, 1, (v) => v + "%"],
    ["zeroAt", 0, 29, 1, (v) => v + "%"],
    ["paperworkWeeks", 0, 26, 1, (v) => v + " weeks"],
    ["reliefShare", 0, 1, 0.05, (v) => Math.round(v * 100) + "%"],
  ];

  /* Build what the engine needs for the current scope: its weeks of history, canals and money at stake. */
  function simScope() {
    const d = district();
    const system = d && usesElephantButte(d) ? "Elephant Butte" : "Amistad-Falcon";
    const members = d ? [d] : HG.districts.filter((x) => !usesElephantButte(x));
    const fips = Array.from(new Set([].concat.apply([], members.map((x) => x.fips))));
    const ids = new Set(members.map((x) => HG.districts.indexOf(x)));
    const canals = U.canals.filter((c) => ids.has(c.district) && c.rank != null);
    const valleyKm = HG.districts.filter((x) => x.fips.some((f) => SIM.valley.indexOf(f) >= 0)).reduce((s, x) => s + x.canalKm, 0);
    const share = members.reduce((s, x) => s + x.canalKm, 0) / valleyKm;
    const start = new Date(SIM.week0 + "T12:00:00Z").getTime(), weeks = [];
    for (let i = 0; i < SIM.nWeeks; i++) {
      const date = new Date(start + i * 7 * 864e5), year = date.getUTCFullYear();
      if (year > 2025) break;                                   // the tested forecasts end in 2025
      const cls = fips.map((f) => SIM.cls[f][i]).filter((ch) => ch !== ".").map(Number);
      const fc = fips.map((f) => SIM.forecast[f][i]).filter((v) => v != null);
      weeks.push({ year, month: date.getUTCMonth() + 1,
                   cls: cls.length ? Math.round(cls.reduce((a, b) => a + b, 0) / cls.length) : null,
                   forecast: fc.length ? fc.reduce((a, b) => a + b, 0) / fc.length : null,
                   pct: SIM.reservoirs[system][i] });
    }
    return { weeks, canals: canals.slice().sort((a, b) => a.rank - b.rank), canalsUnranked: canals,
             demandAf: U.PUBLISHED.valleyIrrigationAf * share, revenueAtStake: U.PUBLISHED.worstCaseRevenue * share,
             share, system, outsideValley: members.some((x) => !x.fips.some((f) => SIM.valley.indexOf(f) >= 0)), members: members.length };
  }

  function renderSim() {
    const d = district(), p = E.makeParams(state.overrides);
    $("view").innerHTML =
      (d ? '<button class="back" data-act="state">&larr; All of Texas</button>' : "") +
      "<h2>Simulation: do nothing, wait, or act</h2><div class=\"sub\">" + U.esc(scopeName()) + ". Every future gets the same weather, the same reservoirs and the same prices. Only the decision differs.</div>" +
      '<div class="card"><div class="seg" id="simMode"><button data-m="replay" class="' + (state.simMode === "replay" ? "on" : "") + '">Replay 2008 to 2025</button><button data-m="forward" class="' + (state.simMode === "forward" ? "on" : "") + '">The next 5 years</button></div>' +
      '<div class="field"><label for="simBudget">Sealing budget in a year you act <output id="simBudgetOut"></output></label><input id="simBudget" type="range" min="0" max="' + $maxBudget() + '" step="' + ($maxBudget() > 200000 ? 5000 : $maxBudget() > 20000 ? 500 : 100) + '" value="' + state.budget + '"></div></div>' +
      '<div id="simResult"></div>' +
      '<details class="assume"><summary>Assumptions you can change (' + SLIDERS.length + ")</summary>" +
      SLIDERS.map(([k, min, max, step, show]) => '<div class="field"><label for="a_' + k + '"><span>' + E.DEFAULTS[k].label + ' <span class="tag ' + E.DEFAULTS[k].tag + '">' + E.DEFAULTS[k].tag + '</span></span><output id="o_' + k + '">' + show(p[k]) + '</output></label><input type="range" data-param="' + k + '" id="a_' + k + '" min="' + min + '" max="' + max + '" step="' + step + '" value="' + p[k] + '"></div>').join("") +
      '<button class="btn small ghost" style="color:var(--blue)" data-act="resetAssume">Reset to defaults</button></details>' +
      '<div id="simNotes"></div>';
    renderSimResult();
  }
  function $maxBudget() { return Math.max(100, Math.ceil(U.planFor(scopeCanals(), 0, null).costAll / 100) * 100); }

  /* A simple line chart as SVG. series = [{ name, color, values: [numbers] }], labels = x-axis labels. */
  function lineChart(series, labels, fmt) {
    const W = 640, H = 240, L = 62, R = 12, T = 12, B = 26;
    const max = Math.max(0, Math.max.apply(null, series.map((s) => Math.max.apply(null, s.values))));
    const min = Math.min(0, Math.min.apply(null, series.map((s) => Math.min.apply(null, s.values))));
    const span = (max - min) || 1;
    const x = (i) => L + (W - L - R) * i / Math.max(1, labels.length - 1), y = (v) => T + (H - T - B) * (1 - (v - min) / span);
    let out = '<svg viewBox="0 0 ' + W + " " + H + '">';
    for (let g = 0; g <= 4; g++) { const v = min + span * g / 4; out += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y(v) + '" y2="' + y(v) + '" stroke="#e3e9f0"/><text x="' + (L - 6) + '" y="' + (y(v) + 4) + '" text-anchor="end">' + fmt(v) + "</text>"; }
    labels.forEach((lab, i) => { if (i % Math.ceil(labels.length / 9) === 0) out += '<text x="' + x(i) + '" y="' + (H - 6) + '" text-anchor="middle">' + lab + "</text>"; });
    series.forEach((s) => { out += '<polyline fill="none" stroke="' + s.color + '" stroke-width="2.6" stroke-linejoin="round" points="' + s.values.map((v, i) => x(i) + "," + y(v)).join(" ") + '"/>'; });
    return out + "</svg>" + '<div class="legend" style="margin-top:6px">' + series.map((s) => '<span><i class="lineKey" style="background:' + s.color + '"></i>' + s.name + "</span>").join("") + "</div>";
  }
  /* Bars for one value per year, with a marker under years flagged true. */
  function yearBars(values, labels, flags, color) {
    const W = 640, H = 170, L = 62, R = 12, T = 10, B = 34, max = Math.max.apply(null, values) || 1;
    const bw = (W - L - R) / values.length;
    let out = '<svg viewBox="0 0 ' + W + " " + H + '"><text x="' + (L - 6) + '" y="' + (T + 8) + '" text-anchor="end">' + shortUsd(max) + '</text><text x="' + (L - 6) + '" y="' + (H - B + 4) + '" text-anchor="end">$0</text>';
    values.forEach((v, i) => {
      const h = (H - T - B) * v / max;
      out += '<rect x="' + (L + i * bw + 2) + '" y="' + (H - B - h) + '" width="' + (bw - 4) + '" height="' + Math.max(h, 0.5) + '" rx="2" fill="' + color + '"><title>' + labels[i] + ": " + U.usd(v) + "</title></rect>";
      if (flags[i]) out += '<circle cx="' + (L + i * bw + bw / 2) + '" cy="' + (H - B + 8) + '" r="3.5" fill="#e0a100"><title>' + labels[i] + ": sealed, but no shortage to fill</title></circle>";
      if (i % 2 === 0) out += '<text x="' + (L + i * bw + bw / 2) + '" y="' + (H - 6) + '" text-anchor="middle">' + String(labels[i]).slice(2) + "</text>";
    });
    return out + "</svg>";
  }
  const shortUsd = (v) => (v < 0 ? "-" + shortUsd(-v) : v >= 1e9 ? "$" + (v / 1e9).toFixed(1) + "B" : v >= 1e6 ? "$" + (v / 1e6).toFixed(v >= 1e7 ? 0 : 1) + "M" : v >= 1e3 ? "$" + Math.round(v / 1e3) + "k" : "$" + Math.round(v));

  function renderSimResult() {
    const scope = simScope(), over = Object.assign({}, state.overrides, { budget: state.budget });
    $("simBudgetOut").textContent = U.usd(state.budget);
    const run = (trigger, extra) => E.simulate(scope, { trigger }, Object.assign({}, over, extra || {}));
    let html = "";

    if (state.simMode === "replay") {
      const runs = POLICIES.map((pol) => run(pol.trigger));
      const [nothing, react, act] = runs;
      const d1 = run("d1"), always = run("always");
      const actLow = run("forecast", { cut: 0.28 }), actHigh = run("forecast", { cut: 0.87 });
      const years = nothing.years.map((y) => y.year);
      html += '<div class="futures">' + POLICIES.map((pol, i) => {
        const t = runs[i].totals, saved = nothing.totals.cost - t.cost;
        return '<div class="future ' + pol.css + '"><span>' + pol.name + "</span><b>" + U.usd(t.cost) + "</b><small>lost crops " + U.usd(t.loss) + " + sealing " + U.usd(t.spend) + "</small>" +
          (i ? "<em>" + (saved >= 0 ? U.usd(saved) + " less than doing nothing" : U.usd(-saved) + " more than doing nothing") + "</em>" : "<small>" + pol.blurb + "</small>") + "</div>";
      }).join("") + "</div>" +
        '<p class="credit" style="margin:8px 0 0">Total over 2008 to 2025 for ' + (scope.members > 1 ? scope.members + " districts on the " + scope.system + " system" : "this district") + ". Lost crops are counted at net revenue per acre-foot of missing irrigation water.</p>" +
        "<h3>Running gain over doing nothing (crop loss avoided minus sealing cost)</h3><div class=\"chart\">" +
        lineChart(POLICIES.slice(1).map((pol, i) => { let sum = 0; return { name: pol.name, color: pol.color, values: runs[i + 1].years.map((y, k) => (sum += nothing.years[k].loss - y.loss - y.spend)) }; }), years, shortUsd) +
        '<p class="credit" style="margin:6px 0 0">The lines are flat in wet years: saved water only counts when there is a shortage to fill. A dip is a year sealing was paid for and not needed.</p></div>' +
        "<h3>Crop loss avoided each year by acting on the forecast</h3><div class=\"chart\">" +
        yearBars(act.years.map((y, i) => Math.max(0, nothing.years[i].loss - y.loss)), years, act.years.map((y) => y.falseAlarm), "#0b63b5") +
        '<div class="legend"><span><i style="background:#e0a100;border-radius:50%"></i>Sealed, but no shortage to fill that year (money spent for nothing)</span></div></div>';

      // The four ledgers.
      const avgWeek = (r) => { const a = r.years.filter((y) => y.acted); return a.length ? "week " + Math.round(a.reduce((s, y) => s + y.actedWeek + 1, 0) / a.length) : "never"; };
      const row = (label, fn, same) => "<tr><td>" + label + "</td>" + (same ? '<td class="r" colspan="3" style="text-align:center">' + fn(nothing) + " in every future</td>" : runs.map((r) => '<td class="r">' + fn(r) + "</td>").join("")) + "</tr>";
      const head = (text) => '<tr><th colspan="4">' + text + "</th></tr>";
      html += "<h3>Four ledgers</h3><div class=\"scroll\" style=\"max-height:none\"><table class=\"t\"><tr><th></th>" + POLICIES.map((pol) => '<th class="r">' + pol.name + "</th>").join("") + "</tr>" +
        head("Public money") + row("Spent on sealing (before)", (r) => U.usd(r.totals.spend)) + row("Relief paid (after the loss)", (r) => U.usd(r.totals.relief)) +
        head("Farm losses") + row("Crop revenue lost", (r) => U.usd(r.totals.loss)) + row("Jobs at risk in the worst year", (r) => U.num(r.totals.jobsWorstYear)) +
        head("Everyday life (indicative)") + row("Weeks with an irrigation shortage", (r) => U.num(r.totals.weeksShort), true) +
        head("Pressure indicators") + row("Weeks in severe drought (D2 or worse)", (r) => U.num(r.totals.weeksD2), true) + row("Years canal work was done", (r) => r.totals.yearsActed + " of " + years.length) + row("Canal work starts, on average", avgWeek) +
        "</table></div>";

      // The receipt: every comparison, including the ones that do not flatter the forecast.
      const diff = (a, b) => a.totals.cost - b.totals.cost;
      const li = (cls, text, tag) => '<li class="' + cls + '">' + text + (tag ? ' <span class="tag ' + tag + '">' + tag + "</span>" : "") + "</li>";
      const vsReact = diff(react, act), vsD1 = diff(d1, act), vsAlways = diff(always, act);
      const better = (v, other) => (Math.abs(v) < 0.005 * act.totals.cost ? "ended level with " + other : v > 0 ? "ended " + U.usd(v) + " ahead of " + other : "ended " + U.usd(-v) + " behind " + other);
      html += "<h3>The receipt</h3><ul class=\"receipt\">" +
        li("for", "<b>Acting on the forecast ended " + U.usd(diff(nothing, act)) + " ahead of doing nothing.</b> Depending on how well the sealant works (28% to 87% in tests), the gain is between " + U.usd(diff(nothing, actLow)) + " and " + U.usd(diff(nothing, actHigh)) + ".", "assumption") +
        li(vsReact > 0 ? "for" : "against", "<b>Acting on the forecast " + better(vsReact, "waiting for a declaration") + ".</b> Waiting sealed in " + react.totals.yearsActed + " years and started around " + avgWeek(react) + " of the year; the forecast sealed in " + act.totals.yearsActed + " years, in March.", "assumption") +
        li(vsD1 > 0 ? "for" : "against", "<b>The forecast " + better(vsD1, "the simple rule \"seal if already in moderate drought\"") + ".</b> In our tests the forecast and this rule are nearly tied, so this line should be small.", "pipeline") +
        li(vsAlways > 0 ? "for" : "against", "<b>The forecast " + better(vsAlways, "sealing every single year") + ".</b> Sealant is cheap next to lost crops, so sealing every year is hard to beat. The forecast's saving is the " + (years.length - act.totals.yearsActed) + " years it skipped.", "assumption") +
        li("against", "<b>False alarms: " + act.totals.falseAlarms + " of " + act.totals.yearsActed + " years.</b> In those years the forecast policy paid " + U.usd(act.plan.spent) + " for sealing and there was no shortage for the saved water to fill.", "pipeline") +
        li("", "<b>Relief follows losses.</b> If " + Math.round(E.makeParams(over).reliefShare * 100) + "% of farm losses are later repaid from public money, relief falls from " + U.usd(nothing.totals.relief) + " to " + U.usd(act.totals.relief) + " while sealing costs " + U.usd(act.totals.spend) + ".", "assumption") +
        "</ul>";
    } else {
      const pNow = district() ? district().pSeason : scopeP0();
      const result = E.forward(scope, POLICIES.map((pol) => ({ trigger: pol.trigger })), over, { years: 5, draws: 300, seed: 11, pNow });
      const max = Math.max.apply(null, result.map((r) => r.summary.cost.high)) || 1;
      const base = result[0].draws;
      html += '<p class="small muted">300 possible five-year futures, each built from whole years of the real 2008 to 2025 record (so droughts keep their real shape and each year keeps the forecast the model really made). Year one leans dry or wet according to this week\'s forecast (' + U.pct(pNow) + "). Bars show the range that 8 in 10 futures fall in; the mark is the middle.</p>" +
        "<h3>Five-year total: lost crops plus sealing</h3><div class=\"card\">" + result.map((r, i) => {
          const s = r.summary.cost, pol = POLICIES[i];
          const gains = r.draws.map((t, k) => base[k].cost - t.cost).sort((a, b) => a - b);
          const mid = gains[Math.floor(gains.length / 2)], worse = gains.filter((g) => g < 0).length;
          return '<div style="margin:10px 0 16px"><div style="display:flex;justify-content:space-between"><b>' + pol.name + "</b><span>" + U.usd(s.low) + " to " + U.usd(s.high) + "</span></div>" +
            '<div class="gauge" style="height:14px"><i style="left:' + (100 * s.low / max) + "%;width:" + Math.max(0.5, 100 * (s.high - s.low) / max) + "%;background:" + pol.color + ';opacity:.55"></i><u style="left:' + (100 * s.mid / max) + '%"></u></div>' +
            '<div class="small muted">Middle: ' + U.usd(s.mid) + (i ? ". Against doing nothing in the same future: " + U.usd(mid) + " better in the middle case; worse off in " + worse + " of " + gains.length + " futures." : "") + "</div></div>";
        }).join("") + "</div>";
    }
    $("simResult").innerHTML = html;

    $("simNotes").innerHTML =
      (scope.outsideValley ? '<p class="note">The published farm-loss figure covers only Cameron, Hidalgo, Starr and Willacy counties. Applying its value per acre-foot here is our extrapolation.</p>' : "") +
      (!district() ? '<p class="small muted">The state run covers the districts on the Amistad-Falcon system. El Paso and Hudspeth districts draw on Elephant Butte; open one of them to simulate it.</p>' : "") +
      "<h3>What the money figures rest on</h3><div class=\"card small\">" +
      '<p><span class="tag published">published</span> A year with no irrigation water costs the Valley ' + U.usd(U.PUBLISHED.worstCaseRevenue) + ' in net crop revenue and 8,404 jobs (<a target="_blank" rel="noopener" href="' + U.PUBLISHED.worstCaseUrl + '">Texas A&amp;M AgriLife, 2023</a>). Full irrigation demand is 1,349,369 acre-feet a year (<a target="_blank" rel="noopener" href="' + U.PUBLISHED.valleyIrrigationUrl + '">Region M Water Plan, Table 2-8</a>, 2011 use). Dividing the two gives about $367 per acre-foot; that division is ours.</p>' +
      '<p><span class="tag assumption">assumption</span> This scope holds ' + Math.round(scope.share * 100) + "% of the Valley districts' canal length, so it is given that share of the water and of the revenue: " + U.usd(scope.revenueAtStake) + " a year at stake.</p>" +
      '<p><span class="tag assumption">assumption</span> How much water farms get is read off reservoir storage with a straight line between the two sliders above. The real rule is an accounting of reserves (<a target="_blank" rel="noopener" href="' + U.PUBLISHED.allocationRule.url + '">' + U.PUBLISHED.allocationRule.text + "</a>): cities are served first and irrigation gets what is left.</p>" +
      '<p><span class="tag pipeline">pipeline</span> Drought classes, reservoir levels and forecasts are the real weekly records. Each forecast was made by a model trained only on earlier years. "Declaration" uses the federal fast-track rule: 8 straight weeks at D2 (<a target="_blank" rel="noopener" href="' + U.PUBLISHED.disasterRule.url + '">' + U.PUBLISHED.disasterRule.text + "</a>).</p>" +
      '<p style="margin:0"><span class="tag assumption">assumption</span> Sealing is one application of sealant on unlined canals, materials only, and it has not been field-tested on the Rio Grande. Permanent lining is a different job: one 3,900-foot main-canal project was budgeted at $5.1 million (<a target="_blank" rel="noopener" href="' + U.PUBLISHED.liningExample.url + '">' + U.PUBLISHED.liningExample.text + "</a>).</p></div>";
  }

  /* ---------- Putting it together ---------- */
  function refresh(refit) {
    document.querySelectorAll("#stepper button").forEach((b) => b.classList.toggle("on", b.dataset.step === state.step));
    $("shell").classList.toggle("wide", state.step === "sim");
    $("scopeBtn").innerHTML = "<small>" + (district() ? "District" : "View") + "</small>" + U.esc(scopeName()) + " &#9662;";
    ({ risk: renderRisk, budget: renderBudget, sim: renderSim })[state.step]();
    styleMap();
    $("view").scrollTop = 0;
    setTimeout(() => { map.invalidateSize(); if (refit) fitMap(); }, 380);   // after the panel finishes resizing
  }
  function setScope(scope) {
    state.scope = scope; state.county = null; state.severity = null;
    state.budget = defaultBudget();
    try { localStorage.setItem("hg-scope", scope === STATE ? "state" : HG.districts[scope].name); } catch (e) { /* storage can be blocked */ }
    history.replaceState(null, "", scope === STATE ? "#state" : "#d=" + encodeURIComponent(HG.districts[scope].name));
    $("onboard").classList.remove("open");
    drawCanals();
    refresh(true);
  }

  /* Clicks inside the panel: every button carries data-act. */
  $("view").addEventListener("click", (e) => {
    const t = e.target.closest("[data-act]");
    if (!t) return;
    const act = t.dataset.act;
    if (act === "go") { state.step = t.dataset.step; refresh(false); }
    if (act === "state") setScope(STATE);
    if (act === "district") setScope(Number(t.dataset.i));
    if (act === "closeCounty") { state.county = null; refresh(false); }
    if (act === "csv") downloadCsv();
    if (act === "resetAssume") { state.overrides = {}; renderSim(); }
    if (act === "canal") {
      const hit = canalShapes.find((s) => s.c.id === Number(t.dataset.id));
      if (hit) { map.fitBounds(hit.shape.getBounds(), { maxZoom: 14, padding: [80, 80] }); hit.shape.openPopup(); }
    }
  });
  $("view").addEventListener("click", (e) => {
    const sev = e.target.closest("#sev button"), mode = e.target.closest("#simMode button");
    if (sev) { state.severity = sev.dataset.p === "" ? null : Number(sev.dataset.p); renderBudget(); }
    if (mode) { state.simMode = mode.dataset.m; renderSim(); }
  });
  $("view").addEventListener("input", (e) => {
    if (e.target.id === "budget") { state.budget = Number(e.target.value); renderBudgetResult(); }
    if (e.target.id === "simBudget") { state.budget = Number(e.target.value); renderSimResult(); }
    if (e.target.dataset.param) {
      const k = e.target.dataset.param, row = SLIDERS.find((s) => s[0] === k);
      state.overrides[k] = Number(e.target.value);
      if (k === "fullAt" || k === "zeroAt") {                   // keep "none" below "all"
        const p = E.makeParams(state.overrides);
        if (p.zeroAt >= p.fullAt) state.overrides.zeroAt = p.fullAt - 1;
      }
      $("o_" + k).textContent = row[4](state.overrides[k]);
      renderSimResult();
    }
  });
  $("stepper").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (b) { state.step = b.dataset.step; refresh(false); }
  });

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
    if (data && data.systems) { state.live = data; showLive(); if (state.scope != null && state.step === "risk") renderRisk(); }
  }).catch(() => { /* keep the saved reading */ });

  /* ---------- Start: use the link, then the remembered choice, else ask ---------- */
  const byName = (name) => HG.districts.findIndex((d) => d.name === name);
  const hash = decodeURIComponent(location.hash.slice(1));
  let saved = null;
  try { saved = localStorage.getItem("hg-scope"); } catch (e) { /* storage can be blocked */ }
  fitMap();
  if (hash === "state") setScope(STATE);
  else if (hash.indexOf("d=") === 0 && byName(hash.slice(2)) >= 0) setScope(byName(hash.slice(2)));
  else if (saved === "state") setScope(STATE);
  else if (saved && byName(saved) >= 0) setScope(byName(saved));
  else { state.scope = STATE; state.budget = defaultBudget(); drawCanals(); refresh(true); openChooser(); }
})();
