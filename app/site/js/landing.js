/*
  landing.js: everything that moves on the intro page.

    1. fills in the numbers from the data files
    2. fades sections in as they scroll into view, and counts numbers up
    3. draws the story map (an SVG) and changes it as each story card reaches the middle
       of the screen: colours, layers, and a smooth zoom from all of Texas to the Valley
*/
(function () {
  "use strict";
  const HG = window.HG, SIM = window.HG_SIM, U = window.HGU;
  const $ = (id) => document.getElementById(id);
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- 1. Numbers ---------- */
  const inDrought = HG.texas.filter((c) => c.dm != null && c.dm >= 2).length;      // D1 or worse
  const warned = HG.river.filter((c) => c.pSeason >= HG.threshold).length;
  const valleyCounty = HG.river.find((c) => c.reservoir === "Amistad-Falcon");
  const resPct = valleyCounty ? valleyCounty.reservoirPct : null;
  const resDate = HG.refresh && HG.refresh.sources && HG.refresh.sources.reservoirs ? HG.refresh.sources.reservoirs.newest : HG.week;
  const plan = U.planFor(U.canals, HG.plan.budget_usd, null);
  const forecastRule = HG.trigger.rules.find((r) => r.name === "Our forecast");
  const d1Rule = HG.trigger.rules.find((r) => r.name === "D1 or worse now");

  $("sDrought").dataset.to = inDrought;
  $("sRes").dataset.to = resPct;
  $("sWarn").dataset.to = warned;
  $("tDrought").textContent = inDrought;
  $("tWeek").textContent = "week of " + U.niceDate(HG.week);
  $("tRes").textContent = resPct;
  $("tResDate").textContent = U.niceDate(resDate);
  $("tWarn").textContent = warned;
  $("tSkill").textContent = "Tested on 2008 to 2025, years the model had not seen: it caught " +
    Math.round(forecastRule.recall * 100) + "% of drought seasons, and about " +
    Math.round((1 - forecastRule.precision) * 100) + " in 100 warnings were false alarms.";
  $("tKm").textContent = U.num(HG.plan.canal_km_in_districts);
  $("tDistricts").textContent = HG.plan.n_districts;
  $("tPlanKm").textContent = U.num(plan.km);
  $("tSaved").textContent = U.num(plan.savedLow) + " to " + U.num(plan.savedHigh);
  $("limitTie").textContent = "Before the season it caught " + Math.round(forecastRule.recall * 100) +
    "% of drought seasons. The simple rule \"already in moderate drought\" caught " + Math.round(d1Rule.recall * 100) +
    "%. The forecast's edge is small; its value is the months of warning.";

  // Insured drought losses by year, added up over the Texas river counties.
  const lossByYear = {};
  Object.values(SIM.insuredDroughtLoss).forEach((years) => {
    for (const y in years) lossByYear[y] = (lossByYear[y] || 0) + years[y];
  });
  const lossYears = Object.keys(lossByYear).map(Number);
  const firstYear = 2000, lastYear = Math.max.apply(null, lossYears);
  const biggest = Math.max.apply(null, Object.values(lossByYear));
  for (let y = firstYear; y <= lastYear; y++) {
    const bar = U.el("div", { "data-tip": y + ": " + U.usd(lossByYear[y] || 0), "data-h": 100 * (lossByYear[y] || 0) / biggest });
    bar.style.setProperty("--d", ((y - firstYear) * 0.03) + "s");
    $("lossBars").appendChild(bar);
  }
  $("lossLastYear").textContent = lastYear;
  $("lossTotal").textContent = U.usd(Object.values(lossByYear).reduce((a, b) => a + b, 0));

  // Figures from named reports (checked against the reports; see common.js).
  const P = U.PUBLISHED;
  $("facts").innerHTML = P.facts.map((f, i) =>
    '<div class="reveal" style="--d:' + (i * 0.1) + 's"><b>' + f.big + "</b><span>" + f.text +
    ' <a href="' + f.url + '" target="_blank" rel="noopener">' + f.source + "</a></span></div>").join("");

  /* ---------- Photos: the hero wall and the moving strip ---------- */
  const riverFips = HG.river.map((c) => c.fips);
  const wall = riverFips.map((f) => U.photo(f, "drought")).concat(riverFips.map((f) => U.photo(f, "county")));
  $("mosaic").innerHTML = wall.slice(0, 28).map((src) => '<img src="' + src + '" alt="" loading="eager">').join("");
  // The strip: river counties first, then a spread of other counties. Listed twice so the loop is seamless.
  const others = HG.texas.filter((c) => riverFips.indexOf(c.fips) < 0 && c.photos.indexOf("county") >= 0)
    .filter((c, i) => i % 12 === 0);
  const strip = HG.river.map((c) => U.countyByFips[c.fips]).concat(others).filter(Boolean);
  const figure = (c) => '<figure><img src="' + U.photo(c.fips, "county") + '" alt="Aerial image of ' + U.esc(c.name) +
    ' County" loading="lazy"><figcaption>' + U.esc(c.name) + " County</figcaption></figure>";
  $("marquee").innerHTML = strip.map(figure).join("") + strip.map(figure).join("");

  /* ---------- 2. Fade-in on scroll, counting numbers, top bar ---------- */
  function countUp(node) {
    const to = Number(node.dataset.to), digits = Number(node.dataset.digits || 0);
    if (reduced || isNaN(to)) { node.textContent = isNaN(to) ? "n/a" : to.toFixed(digits); return; }
    const start = performance.now(), ms = 1400;
    (function tick(now) {
      const t = Math.min(1, (now - start) / ms), eased = 1 - Math.pow(1 - t, 3);
      node.textContent = (to * eased).toFixed(digits);
      if (t < 1) requestAnimationFrame(tick);
    })(start);
  }
  const seen = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      entry.target.classList.add("in");
      entry.target.querySelectorAll("[data-count]").forEach(countUp);
      entry.target.querySelectorAll("[data-h]").forEach((bar) => { bar.style.height = bar.dataset.h + "%"; });
      seen.unobserve(entry.target);
    });
  }, { threshold: 0.15 });
  document.querySelectorAll(".reveal").forEach((node) => seen.observe(node));

  window.addEventListener("scroll", () => {
    const max = document.documentElement.scrollHeight - window.innerHeight;
    $("progress").style.transform = "scaleX(" + (max > 0 ? window.scrollY / max : 0) + ")";
    $("nav").classList.toggle("solid", window.scrollY > 40);
  }, { passive: true });

  /* ---------- 3. The story map ---------- */
  const svg = $("storyMap");
  const NS = "http://www.w3.org/2000/svg";
  // A simple flat projection that is accurate enough at Texas latitudes:
  // squeeze longitude by cos(29 degrees) so shapes are not stretched sideways.
  const K = Math.cos(29 * Math.PI / 180), S = 100;
  const px = (lon) => +(lon * K * S).toFixed(1), py = (lat) => +(-lat * S).toFixed(1);
  const ringPath = (ring) => "M" + ring.map((p) => px(p[0]) + " " + py(p[1])).join("L") + "Z";
  const linePath = (line) => "M" + line.map((p) => px(p[0]) + " " + py(p[1])).join("L");
  const add = (parent, tag, attrs) => {
    const node = document.createElementNS(NS, tag);
    for (const k in attrs) node.setAttribute(k, attrs[k]);
    parent.appendChild(node);
    return node;
  };
  const layer = (name) => add(svg, "g", { class: "layer l-" + name });

  // Layers, bottom to top.
  const gCounties = layer("counties"), gDistricts = layer("districts"), gCanals = layer("canals"),
        gFunded = layer("funded"), gRiver = layer("river"), gLabels = layer("labels");

  const countyNodes = HG.texas.map((c) => {
    const node = add(gCounties, "path", { class: "county", d: c.rings.map(ringPath).join("") });
    return { c, node };
  });
  HG.districts.forEach((d) => add(gDistricts, "path", { class: "district", d: d.rings.map(ringPath).join("") }));
  // One path per canal level (5 paths instead of 7,000) keeps scrolling smooth.
  const canalNodes = {};
  HG.levels.forEach((level) => {
    const d = U.canals.filter((c) => c.level === level).map((c) => linePath(c.line)).join("");
    canalNodes[level] = add(gCanals, "path", { class: "canal", d });
  });
  add(gFunded, "path", { class: "funded", d: plan.funded.map((c) => linePath(c.line)).join("") });
  const riverNodes = HG.riverLine.map((line) => add(gRiver, "path", { class: "riverLine", d: linePath(line), pathLength: 1 }));
  HG.river.forEach((c) => { add(gLabels, "text", { class: "label", x: px(c.lon), y: py(c.lat) }).textContent = c.name; });

  // Bounding boxes to zoom to: all of Texas, the river counties, and the Valley.
  function boxOf(fipsList) {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    HG.texas.forEach((c) => {
      if (fipsList && fipsList.indexOf(c.fips) < 0) return;
      c.rings.forEach((ring) => ring.forEach((p) => {
        const x = px(p[0]), y = py(p[1]);
        if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
      }));
    });
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }
  const BOXES = { texas: boxOf(null), reach: boxOf(riverFips), valley: boxOf(["48061", "48215", "48489"]) };

  // Turn a box into an SVG viewBox that leaves room for the story card on the right.
  function viewFor(box) {
    const W = svg.clientWidth || window.innerWidth, H = svg.clientHeight || window.innerHeight;
    const wide = W > 900;
    const availW = W * (wide ? 0.56 : 0.9), availH = H * (wide ? 0.74 : 0.5);
    const scale = Math.min(availW / box.w, availH / box.h);                 // screen pixels per map unit
    const vw = W / scale, vh = H / scale;
    const cx = box.x + box.w / 2, cy = box.y + box.h / 2;
    const centreX = wide ? 0.31 : 0.5, centreY = wide ? 0.54 : 0.36;        // where on screen the box is centred
    return [cx - vw * centreX, cy - vh * centreY, vw, vh];
  }

  let view = null, tween = 0;
  function applyView(v) {
    view = v;
    svg.setAttribute("viewBox", v.map((n) => n.toFixed(1)).join(" "));
    // The river and labels are sized in map units, so resize them to stay the same on screen.
    const unit = v[2] / (svg.clientWidth || window.innerWidth);              // map units per screen pixel
    riverNodes.forEach((n) => { n.style.strokeWidth = (3.2 * unit).toFixed(2); });
    gLabels.style.fontSize = (11 * unit).toFixed(2) + "px";
    gLabels.style.strokeWidth = (3 * unit).toFixed(2) + "px";
  }
  function zoomTo(name) {
    const target = viewFor(BOXES[name]);
    cancelAnimationFrame(tween);
    if (!view || reduced) { applyView(target); return; }
    const from = view.slice(), start = performance.now(), ms = 1300;
    (function tick(now) {
      const t = Math.min(1, (now - start) / ms);
      const e = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;   // ease in and out
      applyView(from.map((a, i) => a + (target[i] - a) * e));
      if (t < 1) tween = requestAnimationFrame(tick);
    })(start);
  }

  const key = (color, text, line) => '<span><i class="' + (line ? "lineKey" : "") + '" style="background:' + color + '"></i>' + text + "</span>";
  const DM_LEGEND = U.DM_TEXT.map((text, i) => key(U.DM_COLOR[i], text)).join("");
  const TIER_LEGEND = ["Low", "Watch", "Warning"].map((t) => key(U.TIER_COLOR[t], t + (t === "Warning" ? " (25% or more)" : ""))).join("");
  const LEVEL_LEGEND = HG.levels.map((l) => key(U.LEVEL_COLOR[l], l, true)).join("");

  // What the map shows at each story card.
  const STEPS = [
    { zoom: "texas", show: ["counties"], fill: "dm", label: "Drought this week", legend: DM_LEGEND },
    { zoom: "reach", show: ["counties", "river"], fill: "dm", label: "The Rio Grande in Texas", legend: DM_LEGEND + key("#3aa0e6", "Rio Grande", true) },
    { zoom: "reach", show: ["counties", "river", "labels"], fill: "forecast", label: "Six-month drought forecast", legend: TIER_LEGEND },
    { zoom: "valley", show: ["counties", "river", "districts", "canals"], fill: "dark", canals: "plain", label: "Lower Rio Grande Valley: districts and canals", legend: key("#9fc4e6", "Canal", true) + key("#bfe4ff", "District boundary", true) },
    { zoom: "valley", show: ["counties", "river", "canals"], fill: "dark", canals: "levels", label: "Canals by priority", legend: LEVEL_LEGEND },
    { zoom: "valley", show: ["counties", "river", "canals", "funded"], fill: "dark", canals: "levels", label: "The $100,000 plan", legend: key("#5ef2ff", "Sealed under this budget", true) },
  ];
  function setStep(i) {
    const step = STEPS[i];
    ["counties", "river", "districts", "canals", "funded", "labels"].forEach((name) =>
      svg.classList.toggle("show-" + name, step.show.indexOf(name) >= 0));
    countyNodes.forEach(({ c, node }) => {
      let fill = "#16345e";
      if (step.fill === "dm") fill = c.dm == null ? "#16345e" : U.DM_COLOR[c.dm];
      if (step.fill === "forecast" && U.riverByFips[c.fips]) fill = U.TIER_COLOR[U.riverByFips[c.fips].tier];
      node.style.fill = fill;
    });
    HG.levels.forEach((level) => { canalNodes[level].style.stroke = step.canals === "levels" ? U.LEVEL_COLOR[level] : "#9fc4e6"; });
    // The river "draws itself" the first time it appears.
    riverNodes.forEach((n) => { n.style.strokeDasharray = 1; n.style.transition = reduced ? "none" : "stroke-dashoffset 2.6s ease"; n.style.strokeDashoffset = step.show.indexOf("river") >= 0 ? 0 : 1; });
    $("stageLabel").textContent = step.label;
    $("stageLegend").innerHTML = step.legend;
    zoomTo(step.zoom);
  }

  let current = -1;
  const steps = Array.prototype.slice.call(document.querySelectorAll(".story .step"));
  const stepWatcher = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      const i = Number(entry.target.dataset.step);
      steps.forEach((s) => s.classList.toggle("active", s === entry.target));
      if (i !== current) { current = i; setStep(i); }
    });
  }, { rootMargin: "-45% 0px -45% 0px" });   // a card counts as "current" when it crosses the middle of the screen
  steps.forEach((s) => stepWatcher.observe(s));

  setStep(0); current = 0; steps[0].classList.add("active");
  window.addEventListener("resize", () => { view = null; zoomTo(STEPS[Math.max(0, current)].zoom); });
})();
