/*
  common.js: small helpers shared by the intro page (index.html) and the platform (app.html).

  The data itself comes from two generated files (see app/build_site.py):
    window.HG      maps, this week's forecasts, canals, districts, test results
    window.HG_SIM  weekly history from 2008 on, for the simulation
*/
(function () {
  "use strict";
  const HG = window.HG;

  /* ---------- Colours (one place, so the maps, legends and charts always agree) ---------- */
  const DM_COLOR = ["#e6ebf1", "#f6e58a", "#f5c26b", "#ef8f2f", "#d9352b", "#7a0f12"];   // None, D0 .. D4
  const DM_TEXT = ["No drought", "D0 Abnormally dry", "D1 Moderate drought", "D2 Severe drought",
                   "D3 Extreme drought", "D4 Exceptional drought"];
  const TIER_COLOR = { Low: "#3f8f5f", Watch: "#e0a100", Warning: "#c9372c" };
  const LEVEL_COLOR = { "Inspect first": "#c9372c", Watch: "#e0a100", Low: "#3f8f5f",
                        "Unknown soil": "#8a94a3", Drain: "#a9bdd1" };

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
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  /* ---------- Canals as objects (the data file stores them as short lists to stay small) ---------- */
  const canals = HG.canals.map((c, i) => ({
    id: i, name: HG.canalNames[c[0]] || "Unnamed canal", soil: HG.soils[c[1]], level: c[2], fips: c[3],
    km: c[4], rate: c[5], p: c[6], district: c[7], rank: c[8], usd: c[9], line: c[10],
  }));
  const countyByFips = {};
  HG.texas.forEach((c) => { countyByFips[c.fips] = c; });
  const riverByFips = {};
  HG.river.forEach((c) => { riverByFips[c.fips] = c; });

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
    const result = window.HGEngine.fundCanals(ordered, budget, p);
    const days = a.days_one_application_lasts;
    return {
      ordered, funded: result.funded, fundedIds: new Set(result.funded.map((c) => c.id)),
      spent: result.spent, km: result.km,
      savedLow: window.HGEngine.savedAcreFeet(result.gallonsPerDay, days, a.sealant_cut_low),
      savedHigh: window.HGEngine.savedAcreFeet(result.gallonsPerDay, days, a.sealant_cut_high),
      costAll: ordered.reduce((s, c) => s + c.usd, 0),
      sqft: result.km * window.HGEngine.FEET_PER_KM * a.wetted_width_ft,
    };
  }

  /* Path to one of a county's photos. kind = "county" (aerial), "drought" (close-up) or "ground". */
  const photo = (fips, kind) => "photos/" + fips + "-" + kind + ".jpg";

  /* Tiny helper to build HTML elements: el("div", {class: "x"}, "text or html") */
  function el(tag, attrs, html) {
    const node = document.createElement(tag);
    for (const k in attrs || {}) node.setAttribute(k, attrs[k]);
    if (html != null) node.innerHTML = html;
    return node;
  }

  window.HGU = { DM_COLOR, DM_TEXT, TIER_COLOR, LEVEL_COLOR, PUBLISHED, usd, num, pct, niceDate, esc,
                 canals, countyByFips, riverByFips, actionFor, tierFor, planFor, photo, el };
})();
