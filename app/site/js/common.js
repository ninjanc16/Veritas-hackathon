/*
  common.js: small helpers shared by the intro page (index.html) and the platform (app.html).

  The data itself comes from two generated files (see app/build_site.py):
    window.HG      maps, this week's forecasts, canals, districts, test results
    window.HG_SIM  weekly history from 2008 on, for the simulation

  The formatting and planning rules are in js/logic.js (window.HGLogic), which must load first.
*/
(function () {
  "use strict";
  const HG = window.HG;

  /* ---------- Theme: dark is the default; the choice is remembered in this browser ---------- */
  let theme = "dark";
  try { theme = localStorage.getItem("hg-theme") || "dark"; } catch (e) { /* storage can be blocked */ }
  document.documentElement.dataset.theme = theme;

  /* ---------- Colours (one place, so the maps, legends and charts always agree) ----------
     They are read from the stylesheet (css/site.css), so the dark and light themes each
     have their own set. readTheme() fills the lists below again after the theme changes. */
  const DM_COLOR = [];                                       // None, D0 .. D4
  const DM_TEXT = ["No drought", "D0 Abnormally dry", "D1 Moderate drought", "D2 Severe drought",
                   "D3 Extreme drought", "D4 Exceptional drought"];
  const TIER_COLOR = {}, LEVEL_COLOR = {};
  function readTheme() {
    const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    DM_COLOR.splice(0, 9, css("--dm0"), css("--dm1"), css("--dm2"), css("--dm3"), css("--dm4"), css("--dm5"));
    Object.assign(TIER_COLOR, { Low: css("--low"), Watch: css("--watch"), Warning: css("--warning") });
    Object.assign(LEVEL_COLOR, { "Inspect first": css("--inspect"), Watch: css("--watch"), Low: css("--low"),
                                 "Unknown soil": css("--unknown"), Drain: css("--drain") });
  }
  readTheme();
  function setTheme(next) {
    theme = next; document.documentElement.dataset.theme = next;
    try { localStorage.setItem("hg-theme", next); } catch (e) { /* storage can be blocked */ }
    readTheme();
  }

  /*
    Figures from named reports. Each was opened and checked against the report itself on
    2026-11-14 (see "checked" on each line). Anything we could not confirm is not used.
  */
  const AGRILIFE = "https://agecoext.tamu.edu/wp-content/uploads/2024/02/2023.08.Estimated-Economic-Impacts-of-Irrigation-Water-Shortages-on-LRGV-Agriculture.pdf";
  const REGION_M = "https://www.lrgvdc.org/downloads/regionm/waterplan/Ch_2_M_2026_Final_Draft.pdf";
  const PUBLISHED = {
    // Texas A&M AgriLife, CNAS Report 2023-08, Table 5. A year with NO irrigation water in Cameron,
    // Hidalgo, Starr and Willacy counties: net crop revenue lost, total economic output lost, jobs.
    worstCaseRevenue: 495823372,
    worstCaseOutput: 993246334,
    worstCaseJobs: 8404,
    worstCaseUrl: AGRILIFE,
    // 2026 Region M Water Plan, Chapter 2, Table 2-8: irrigation use in those four counties in 2011,
    // a high-demand year with full reservoirs (acre-feet). We added the four county figures ourselves.
    valleyIrrigationAf: 1349369,
    valleyIrrigationUrl: REGION_M,
    // The cards on the intro page. Each links to the document the figure was read from.
    facts: [
      { big: "$495.8 million", text: "Net crop revenue the Valley would lose in one year with no irrigation water, with 8,404 jobs. A worst case, not an observed loss.",
        source: "Texas A&M AgriLife, 2023", url: AGRILIFE },
      { big: "$280 million", text: "Federal grant announced in March 2025 for Valley farmers who lost water deliveries in 2023 and 2024. Paid after the loss.",
        source: "USDA", url: "https://www.fsa.usda.gov/news-events/news/03-20-2025/usda-announces-280-million-grant-agreement-support-rio-grande-valley" },
      { big: "865,139 acre-feet", text: "Mexico's water-delivery deficit when the five-year treaty cycle closed on October 24, 2025 (provisional).",
        source: "International Boundary and Water Commission", url: "https://ibwcsftpstg.blob.core.windows.net/wad/WeeklyReports/Current_Cycle.pdf" },
      { big: "54,000 to 223,000", text: "Acre-feet a year that better canal efficiency could save across 28 Valley districts. A preliminary estimate from 1998.",
        source: "Fipps, Texas A&M", url: "https://gfipps.tamu.edu/files/2019/12/RGV-Potential-Water-Savings.pdf" },
    ],
    // Other checked sources the platform cites.
    allocationRule: { text: "30 Texas Administrative Code 303.21 and 303.22", url: "https://www.law.cornell.edu/regulations/texas/30-Tex-Admin-Code-SS-303-22" },
    disasterRule: { text: "7 CFR 759.5(a)", url: "https://www.ecfr.gov/current/title-7/section-759.5" },
    liningExample: { text: "Hidalgo County Irrigation District No. 1 application to Reclamation, 2023", url: "https://www.usbr.gov/watersmart/weeg/docs/2023/HidalgoCountyIDNo1_508.pdf" },
  };

  /* ---------- Formatting: the functions live in js/logic.js, which has no page code and is tested ---------- */
  const { usd, num, pct, niceDate, esc, workTime } = window.HGLogic;

  /* ---------- Canals as objects (the data file stores them as short lists to stay small) ---------- */
  const KINDS = ["Irrigation canal", "Ditch", "Drain"];        // what OpenStreetMap calls the line (null = it does not say)
  const canals = HG.canals.map((c, i) => ({
    id: i, name: HG.canalNames[c[0]] || "Unnamed canal", soil: c[1] == null ? null : HG.soils[c[1]], level: c[2], fips: c[3],
    km: c[4], rate: c[5], p: c[6], district: c[7], rank: c[8], usd: c[9], line: c[10],
    kind: c[11] == null ? null : KINDS[c[11]],                 // irrigation canal, ditch or drain
    piped: c[12] === 1,                                        // OpenStreetMap maps most of it underground
    source: c[13] === 1 ? "OpenStreetMap" : "USGS",
  }));
  const countyByFips = {};
  HG.texas.forEach((c) => { countyByFips[c.fips] = c; });
  const riverByFips = {};
  HG.river.forEach((c) => { riverByFips[c.fips] = c; });

  /* The rules that read the data (advice, tier, budget plan, canal numbers) are in js/logic.js too.
     They are bound to the real data here, once, and published under the names they always had. */
  const logic = window.HGLogic.makeLogic({ HG, SIM: window.HG_SIM, canals, published: PUBLISHED }, window.HGEngine);
  const { actionFor, tierFor, planFor, canalNumbers, USD_PER_AF } = logic;

  /* Path to one of a county's photos. kind = "county" (aerial), "drought" (close-up) or "ground". */
  const photo = (fips, kind) => "photos/" + fips + "-" + kind + ".jpg";

  /* Tiny helper to build HTML elements: el("div", {class: "x"}, "text or html") */
  function el(tag, attrs, html) {
    const node = document.createElement(tag);
    for (const k in attrs || {}) node.setAttribute(k, attrs[k]);
    if (html != null) node.innerHTML = html;
    return node;
  }

  window.HGU = { DM_COLOR, DM_TEXT, TIER_COLOR, LEVEL_COLOR, PUBLISHED, USD_PER_AF, usd, num, pct, niceDate, esc,
                 canals, countyByFips, riverByFips, actionFor, tierFor, planFor, canalNumbers, workTime, photo, el,
                 readTheme, setTheme, theme: () => theme, logic };
})();
