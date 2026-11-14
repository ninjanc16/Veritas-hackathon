"""
export_pitch_kit.py - writes the "pitch kit" for the teammate who makes the video.

It writes ONLY inside app/pitch_kit/ :
    numbers.md   every number in metrics.json (the only place the video may copy numbers from)
    writeup.md   a draft of the one-page write-up, filled from metrics.json
    explain.md   plain question-and-answer sheet so the whole team can explain the project
    story.md     four demo moments, each with a link that opens the app on that county
    charts/      four standalone chart files (HTML)

Rules it follows (plain English, for the judges):
  * It never computes a result. Every number is copied from metrics.json.
  * The first line of every file says whether the numbers are DEMO, PROVISIONAL or FINAL.
  * Anything we do not know yet is written as [TEAM: ...] so nobody forgets to fill it in.

Run:  python app/export_pitch_kit.py
"""
import html
import logging
import sys
from pathlib import Path
from urllib.parse import urlencode

import plotly.graph_objects as go
from plotly.offline import get_plotlyjs
from plotly.subplots import make_subplots

# Make "import app.xxx" work when this file is run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
logging.getLogger("streamlit").setLevel(logging.ERROR)   # theme.py imports Streamlit; keep this script quiet
from app import theme                                           # noqa: E402
from app.contract import REPO_ROOT, load                       # noqa: E402

OUT_DIR = REPO_ROOT / "app" / "pitch_kit"
APP_URL = "[TEAM: paste the live app link here]"

STATUS_LINES = {
    "DEMO": "STATUS: DEMO DATA - DO NOT USE",
    "PROVISIONAL": "STATUS: PROVISIONAL - DO NOT USE IN THE FINAL VIDEO OR WRITE-UP",
    "FINAL": "STATUS: FINAL",
}


def status_of(source, metrics):
    """DEMO when the fake files are showing, PROVISIONAL until the pipeline locks numbers, then FINAL."""
    if source == "demo":
        return "DEMO"
    return "FINAL" if metrics["is_final"] else "PROVISIONAL"


def write_text(path, text):
    """Write a file - but refuse to write anywhere outside app/pitch_kit/."""
    path = Path(path).resolve()
    if OUT_DIR.resolve() not in path.parents:
        raise ValueError(f"refusing to write outside app/pitch_kit: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Small formatting helpers
# ---------------------------------------------------------------------------
def fmt(v):
    """Show a value as text. Missing values (None) show as 'n/a'."""
    return "n/a" if v is None else str(v)


def md_table(headers, rows):
    """A Markdown table from a header list and a list of rows."""
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(fmt(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# numbers.md - every number in metrics.json, grouped, nothing computed
# ---------------------------------------------------------------------------
def flatten(prefix, value):
    """Turn nested dicts/lists into ('key.path[0].name', value) pairs."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield from flatten(f"{prefix}.{k}" if prefix else k, v)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from flatten(f"{prefix}[{i}]", v)
    else:
        yield prefix, value


def numbers_md(metrics, status):
    # Which top-level keys go in which group. 'season' and 'year' are split in two:
    # their per_river part belongs with "other rivers".
    season = {k: v for k, v in metrics["season"].items() if k != "per_river"}
    year = {k: v for k, v in metrics["year"].items() if k != "per_river"}
    setup_keys = ["contract_version", "generated_at", "is_final", "focus_river", "training_scope",
                  "n_rows", "n_focus_rows", "n_counties", "n_focus_counties", "horizon_weeks",
                  "train_years", "val_years", "test_years", "latest_week", "miss_cost"]
    groups = [
        ("Setup", {k: metrics[k] for k in setup_keys if k in metrics}),
        ("4-week alert", {k: metrics[k] for k in ("policies", "headline", "onset", "events",
                                                  "cost_sensitivity", "year_by_year") if k in metrics}),
        ("6-month outlook", {"season": season}),
        ("12-month outlook", {"year": year}),
        ("Other rivers", {"per_river": metrics["per_river"],
                          "season.per_river": metrics["season"]["per_river"],
                          "year.per_river": metrics["year"]["per_river"]}),
        ("Failure examples", {"failure_examples": metrics["failure_examples"]}),
        ("Ablations and checks", {k: metrics[k] for k in ("ablations", "shuffled_auc_mean",
                                                          "feature_importance") if k in metrics}),
        ("Limits", {"limits": metrics["limits"]}),
    ]
    # Anything the pipeline adds later still shows up, so no number is ever left out.
    used = set(setup_keys) | {"policies", "headline", "onset", "events", "cost_sensitivity",
                              "year_by_year", "season", "year", "per_river", "failure_examples",
                              "ablations", "shuffled_auc_mean", "feature_importance", "limits"}
    extra = {k: v for k, v in metrics.items() if k not in used}
    if extra:
        groups.append(("Other keys", extra))

    lines = [STATUS_LINES[status], "",
             "# Numbers for the video and write-up",
             "Copy numbers only from this file, and only when the first line says STATUS: FINAL.",
             "Every value below is copied from reports/metrics.json. Nothing is computed here.", ""]
    for title, content in groups:
        lines += [f"## {title}", ""]
        for key, value in content.items():
            for path, leaf in flatten(key, value):
                lines.append(f"- `{path}`: {fmt(leaf)}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# writeup.md - draft of the one-page write-up, in the hackathon's template headings
# ---------------------------------------------------------------------------
def writeup_md(metrics, status):
    m = metrics
    pol = m["policies"]
    sf, yf, h, on = m["season"]["focus"], m["year"]["focus"], m["headline"], m["onset"]
    honesty = "passed" if h["honesty_check_pass"] else "did NOT pass"
    four_week = md_table(["Rule", "Cost", "Precision", "Recall"],
                         [[p["name"], p["cost"], p["precision"], p["recall"]] for p in pol])
    six_month = md_table(["Rule", "Cost", "Precision", "Recall"], [
        ["Our system", sf["system_cost"], sf["precision"], sf["recall"]],
        ["Persistence (D2 or worse now)", sf["persistence_cost"], "-", "-"],
        ["D1 or worse now", sf["d1_rule_cost"], "-", "-"],
        ["Usual for the county", sf["usual_cost"], "-", "-"]])
    twelve_month = md_table(["Rule", "Average error (weeks)"], [
        ["Our system", yf["mae_system"]], ["Same as now", yf["mae_same_as_now"]],
        ["Same as last year", yf["mae_last_year"]], ["Usual for the county", yf["mae_usual"]]])
    rivers = md_table(["River", "Our cost", "Best simple rule", "Its cost"],
                      [[r["river"], r["system_cost"], r["best_rule"], r["best_rule_cost"]]
                       for r in m["per_river"]])
    fail = m["failure_examples"][0]
    limits = "\n".join(f"- {s}" for s in m["limits"])

    return f"""{STATUS_LINES[status]}

# Rio Grande Farm Drought Outlook

**Track:** AI + Climate  |  **Team:** [TEAM: names and schools - no emails in the repo]

## The problem
Along the Rio Grande, drought is the normal risk, and it forces expensive decisions: sell cattle or
buy hay, plant or leave a field fallow, file for disaster aid or not. Farmers get a weekly map of
where drought is now (the U.S. Drought Monitor), but not a county-level answer to "what is likely here
next month, next season and next year?" Our users are ranchers and irrigated-crop farmers in
{m["n_focus_counties"]} counties in Colorado, New Mexico and Texas, and the county Farm Service Agency
offices and irrigation districts that work with them. [TEAM: name one real irrigation district after
checking it.]

## What we built
- **4-week alert:** a Low, Watch or Warning tier for severe drought (D2 or worse) in the next 4 weeks.
- **6-month outlook:** the chance that a county hits 8 straight weeks of severe drought in the next 6
  months, the trigger used by a federal livestock aid program.
- **12-month outlook:** about how many weeks of severe drought to expect in the next year, shown next
  to what is usual for the county and its typical error.
- **App:** {APP_URL}

## What we added
1. **A target that matches a real farm rule:** the 6-month outlook predicts the 8-straight-weeks trigger
   used by a federal aid program, not a generic drought index.
2. **Longer outlooks, tested honestly:** 6 and 12 months, each against "the future equals today" and
   "the usual for this county".
3. **A transfer test:** a model built on the {m["focus_river"]}, tried unchanged on four other rivers.
   It carries over in some places and breaks in others. That is a finding, not something to hide.

## How it works
- **Goes in:** weekly county drought maps from the U.S. Drought Monitor, the county's neighbors, and the
  Pacific El Nino index. [TEAM: Pipeline owner to confirm the exact inputs.]
- **Comes out:** a tier and risk score (4 weeks), a percent (6 months) and a number of weeks (12 months).
- **Model:** random forests trained on {m["training_scope"]}.
- **Time split:** the 4-week alert trained on {m["train_years"][0]} to {m["train_years"][1]}, tuned on
  {m["val_years"][0]} to {m["val_years"][1]}, tested on {m["test_years"][0]} to {m["test_years"][1]}. Each
  outlook test year is predicted by a model trained only on earlier years.
- **Baselines:** "the future equals today", "D1 or worse now", "getting worse", "typical for the time
  of year", and "usual for the county".
- **Leakage checks:** time splits, leakage tests, and a shuffled-label check (average AUC
  {m["shuffled_auc_mean"]}).

## Results
Cost = {m["miss_cost"]} x missed droughts + false alarms. That cost rule is our assumption, not a farmer's number.

**4-week alert, {m["focus_river"]} test years.** Honesty check (beats every simple rule): {honesty}.

{four_week}

**6-month outlook.** Beats every baseline: {"yes" if sf["beats_every_baseline"] else "no"}.

{six_month}

**12-month outlook.** Beats every baseline: {"yes" if yf["beats_every_baseline"] else "no"}.

{twelve_month}

**Other rivers.** The model was trained on the {m["focus_river"]} only:

{rivers}

**A weak result.** On counties not yet in severe drought (the hard part), our system cost
{on["system_cost"]} against {on["best_rule_cost"]} for the best simple rule ({on["best_rule"]}).

**A failure example.** {fail["date"]}, {fail["county"]}, {fail["state"]} ({fail["product"]}): {fail["what_happened"]}

**What the results do not show:**
{limits}

## What we'd do next
Snowpack and river flow as inputs, the real grazing-period rule, a rancher's own cost numbers, and
crop-loss data to test the link to dollars.

## Sources
- Drought data: U.S. Drought Monitor (NDMC, USDA, NOAA), https://droughtmonitor.unl.edu ; county archive by
  the Montana Climate Office [TEAM: add link]
- ENSO index: NOAA Climate Prediction Center, https://www.cpc.ncep.noaa.gov
- App libraries: pandas https://pandas.pydata.org , pyarrow https://arrow.apache.org/docs/python ,
  Streamlit https://streamlit.io , Plotly https://plotly.com/python , pytest https://pytest.org
- Modeling libraries: [TEAM: Pipeline owner to list]
- AI tools used, and what for: [TEAM: the hackathon rules require every AI tool to be credited - list them here]
"""


# ---------------------------------------------------------------------------
# explain.md - the question-and-answer sheet (answers in plain words)
# ---------------------------------------------------------------------------
def explain_md(metrics, status):
    m = metrics
    sf, yf, on = m["season"]["focus"], m["year"]["focus"], m["onset"]
    ohio = next((r for r in m["per_river"] if r["river"] == "Ohio"), None)
    ohio_text = (f"On the Ohio our system cost {ohio['system_cost']} against {ohio['best_rule_cost']} for "
                 f"the best simple rule ({ohio['best_rule']})." if ohio else "[Ohio is not in metrics.json yet]")
    qa = [
        ("What is the U.S. Drought Monitor, and what do D0 to D4 mean?",
         "A map drawn every week by experts at NDMC, USDA and NOAA that shows how dry each place is. "
         "The classes go from D0 (abnormally dry) through D1 (moderate), D2 (severe) and D3 (extreme) "
         "to D4 (exceptional). We forecast their map, not the weather itself."),
        ("What exactly does each of the three products predict?",
         "The 4-week alert says whether a county is likely to reach D2 or worse within 4 weeks (Low, Watch or "
         "Warning). The 6-month outlook gives the chance of 8 straight weeks at D2 or worse in the next 26 "
         "weeks. The 12-month outlook estimates how many of the next 52 weeks will be at D2 or worse."),
        ("What is a random forest, in plain words? Why use it here?",
         "It is a crowd of many small decision trees. Each tree sees a slightly different random slice of the "
         "data, and their answers are combined by voting or averaging. It needs little tuning, copes with "
         "inputs on different scales, and is hard to overfit. That suits a small, noisy dataset."),
        ("What goes into the model? What does 'neighbors within 150 km' mean?",
         "The county's own recent drought history, the drought in nearby counties, the Pacific El Nino "
         "index and the time of year. 'Neighbors within 150 km' means we average the drought class of "
         "counties whose centers are within 150 km, because drought moves across borders. "
         "[TEAM: Pipeline owner to confirm the exact inputs and the 150 km figure.]"),
        ("Why split by time, and not at random?",
         "The real job is predicting the future. Drought weeks next to each other look almost identical, so a "
         "random split lets the model peek at the answer through a neighboring week and the score looks "
         "better than it is. A time split trains on the past and tests on years it never saw."),
        ("What is leakage, and how did we check for it?",
         "Leakage is when information from the future sneaks into training. We guard against it with "
         "time-based splits, automated leakage tests, and a shuffled-label check: with the answers "
         f"scrambled, the model's AUC should be near 0.5. Ours was {m['shuffled_auc_mean']}."),
        ("What is the persistence baseline? What is climatology?",
         "Persistence is 'the future equals today': warn if the county is in severe drought right now. "
         "Climatology is 'the usual for this county': what normally happens, ignoring today. A forecast "
         "is only useful if it beats both."),
        ("What are precision and recall, and why not report accuracy?",
         "Precision: of the warnings we gave, how many were followed by severe drought. Recall: of the "
         "real droughts, how many we warned about. Accuracy can look great while being useless, for "
         "example a system that never warns scores well in a place where drought is rare."),
        ("Where does 'a miss costs 3 false alarms' come from, and why does that give a 0.25 threshold?",
         f"It is our assumption (miss cost = {m['miss_cost']}), not a farmer's number. If a miss is "
         f"{m['miss_cost']} times worse than a false alarm, it pays to warn whenever the chance is at "
         f"least 1 divided by (1 + {m['miss_cost']}). The 6-month threshold in metrics.json is "
         f"{m['season']['threshold']}."),
        ("Why does the 12-month outlook predict a number of weeks, and not yes or no?",
         "A yes-or-no warning a year ahead is nearly always 'yes' on the Rio Grande, so 'always warn' "
         "beats any model. A number of weeks is something a rancher can plan around. It is a planning "
         f"range, not a precise forecast: the typical error is about {yf['mae_system']} weeks, on an "
         f"average of {yf['mean_weeks']} weeks."),
        ("Why does the Rio Grande model fail on the Ohio?",
         "The model learned a place where drought is the norm. On the Ohio severe drought is rare, so "
         f"what it learned does not carry over. {ohio_text}"),
        ("What are the three weakest points of this project?",
         f"1) Onset: for counties not yet in severe drought our system cost {on['system_cost']} against "
         f"{on['best_rule_cost']} for the best simple rule ({on['best_rule']}). "
         f"2) The 6-month margin: our cost {sf['system_cost']} against {sf['d1_rule_cost']} for the "
         "'D1 or worse now' rule, so much of the skill is persistence. "
         f"3) Small sample: the {m['n_focus_counties']} Rio Grande counties move together, so the real "
         "sample is far smaller than the row count."),
        ("Which parts did AI tools write, and how did we check them?",
         "[TEAM: write this yourselves, honestly - which AI tools were used for what, and how each part "
         "was checked (tests, reading the code, comparing with the numbers in metrics.json).]"),
    ]
    lines = [STATUS_LINES[status], "", "# Explain sheet",
             "Everyone on the team reads this before recording the video.", ""]
    for i, (q, a) in enumerate(qa, 1):
        lines += [f"## {i}. {q}", a, ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# story.md - four demo moments, picked by simple rules from the handoff files
# ---------------------------------------------------------------------------
def link(river, fips, view):
    """A link that opens the app on one river, county and tab."""
    return f"{APP_URL}/?" + urlencode({"river": river, "fips": fips, "view": view})


def story_md(pred, latest, metrics, status):
    focus = metrics["focus_river"]
    rg = pred[pred["river"] == focus]
    lines = [STATUS_LINES[status], "", "# Demo story: four moments",
             "Each moment was picked by a fixed rule from the handoff files (not hand-picked).", ""]

    # 1) A county the system warned about BEFORE it entered severe drought, and drought followed.
    hit = rg[rg["alarm_system"] & (rg["cls"] < 3) & (rg["y"] == 1)]
    lines.append("## 1. A warning before the drought arrived")
    if hit.empty:
        lines.append("Rule: highest-risk alarm on a county not yet in D2 where D2 followed. None found.")
    else:
        r = hit.sort_values(["p_model", "date"], ascending=[False, True]).iloc[0]
        lines += ["Rule: the alarm with the highest risk score on a county NOT yet in D2, where D2 followed "
                  "within 4 weeks.",
                  f"- {r['county']}, {r['state']}, week of {r['date']:%b %d, %Y}",
                  f"- In the app: Replay tab, year {r['date'].year}, week of {r['date']:%b %d}",
                  f"- Link: {link(r['river'], r['fips'], 'Replay')}"]
    lines.append("")

    # 2) The first failure example from metrics.json (said out loud: one weak result).
    fail = metrics["failure_examples"][0]
    lines.append("## 2. A failure, said out loud")
    lines.append("Rule: the first entry of failure_examples in metrics.json.")
    lines.append(f"- {fail['date']}, {fail['county']}, {fail['state']}: {fail['what_happened']}")
    found = pred[(pred["county"] == fail["county"]) & (pred["state"] == fail["state"])]
    if not found.empty:
        lines.append(f"- Link: {link(found.iloc[0]['river'], found.iloc[0]['fips'], 'Replay')}")
    else:
        lines.append("- Link: [TEAM: county not found in the handoff files - open it by hand]")
    lines.append("")

    # 3) This week's highest-risk county on the focus river.
    now = latest[latest["river"] == focus].sort_values(["p_model", "p_season", "fips"],
                                                       ascending=[False, False, True])
    lines.append("## 3. This week")
    lines.append("Rule: the focus-river county with the highest 4-week risk score this week.")
    if now.empty:
        lines.append("- None found.")
    else:
        r = now.iloc[0]
        lines += [f"- {r['county']}, {r['state']}: {r['tier']}, week of {r['date']:%b %d, %Y}",
                  f"- Link: {link(r['river'], r['fips'], 'This week')}"]
    lines.append("")

    # 4) One Ohio county where the model does not carry over.
    lines.append("## 4. Where it stops working")
    lines.append("Rule: the Ohio county with the most missed droughts in the test years "
                 "(counted in the app, not a reported result).")
    ohio = pred[pred["river"] == "Ohio"]
    missed = ohio[(~ohio["alarm_system"]) & (ohio["y"] == 1)]
    if ohio.empty:
        lines.append("- Ohio is not in the handoff files.")
    else:
        fips = missed.groupby("fips").size().idxmax() if not missed.empty else ohio.iloc[0]["fips"]
        r = ohio[ohio["fips"] == fips].iloc[0]
        lines += [f"- {r['county']}, {r['state']}",
                  f"- Link: {link('Ohio', fips, 'Other rivers and misses')}"]
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# charts/ - four standalone plotly files (each opens in any browser)
# ---------------------------------------------------------------------------
TIER_COLOR = theme.TIER_COLOR            # same earth tones as the app


def save_chart(fig, name, status):
    """Add the status to the title (unless FINAL) and save as an HTML file."""
    if status != "FINAL":
        fig.update_layout(title_text=f"{fig.layout.title.text} ({STATUS_LINES[status][8:]})")
    # "directory" = the page loads plotly.min.js from the SAME folder (written once in build_charts),
    # so opening a chart never downloads a script from the internet. Fixed div id = same file each run.
    theme.style_fig(fig)                                   # same fonts and colors as the app
    fig.update_layout(paper_bgcolor="#f4f1e8", plot_bgcolor="#f4f1e8")   # warm paper, not transparent
    page = fig.to_html(include_plotlyjs="directory", full_html=True, div_id="chart")
    write_text(OUT_DIR / "charts" / name, page)


def build_charts(latest, metrics, status):
    m = metrics
    write_text(OUT_DIR / "charts" / "plotly.min.js", get_plotlyjs())   # local copy of the chart library
    # 1) The 4-week rules compared by cost (lower is better). Our system in blue.
    names = [p["name"] for p in m["policies"]]
    colors = [theme.CHART_COLORS[1] if p["column"] == "alarm_system" else "#b9b49f" for p in m["policies"]]
    fig = go.Figure(go.Bar(x=[p["cost"] for p in m["policies"]], y=names, orientation="h",
                           marker_color=colors))
    fig.update_layout(title_text="4-week alert: cost by rule (lower is better)", xaxis_title="Cost",
                      yaxis=dict(autorange="reversed"))
    save_chart(fig, "four_week_policies.html", status)

    # 2) The 12-month average errors (lower is better).
    yf = m["year"]["focus"]
    bars = {"Our system": yf["mae_system"], "Same as now": yf["mae_same_as_now"],
            "Same as last year": yf["mae_last_year"], "Usual for the county": yf["mae_usual"]}
    fig = go.Figure(go.Bar(x=list(bars), y=list(bars.values()),
                           marker_color=[theme.CHART_COLORS[1], "#b9b49f", "#b9b49f", "#b9b49f"]))
    fig.update_layout(title_text="12-month outlook: average error in weeks (lower is better)",
                      yaxis_title="Weeks")
    save_chart(fig, "twelve_month_error.html", status)

    # 3) The three other-rivers tables as one chart: our system vs the best simple rule.
    fig = make_subplots(rows=3, cols=1, vertical_spacing=0.12, subplot_titles=(
        "4-week alert: cost", "6-month outlook: cost", "12-month outlook: average error (weeks)"))
    tables = [(m["per_river"], "system_cost", "best_rule_cost"),
              (m["season"]["per_river"], "system_cost", "best_rule_cost"),
              (m["year"]["per_river"], "mae_system", "mae_best_baseline")]
    for row, (rows, ours, best) in enumerate(tables, 1):
        rivers = [r["river"] for r in rows]
        fig.add_trace(go.Bar(x=rivers, y=[r[ours] for r in rows], name="Our system",
                             marker_color=theme.CHART_COLORS[1], showlegend=(row == 1), legendgroup="a"), row=row, col=1)
        fig.add_trace(go.Bar(x=rivers, y=[r[best] for r in rows], name="Best simple rule",
                             marker_color="#b9b49f", showlegend=(row == 1), legendgroup="b"), row=row, col=1)
    fig.update_layout(title_text="Other rivers: our system vs the best simple rule (lower is better)",
                      barmode="group", height=900)
    save_chart(fig, "other_rivers.html", status)

    # 4) This week's map of the focus river.
    now = latest[latest["river"] == m["focus_river"]]
    fig = go.Figure()
    for tier, color in TIER_COLOR.items():
        sub = now[now["tier"] == tier]
        fig.add_trace(go.Scatter(x=sub["lon"], y=sub["lat"], mode="markers", name=tier,
                                 text=[html.escape(f"{c}, {s}") for c, s in zip(sub["county"], sub["state"])],
                                 hoverinfo="text",
                                 marker=dict(size=14, color=color)))
    fig.update_yaxes(scaleanchor="x", scaleratio=1, title="Latitude")
    fig.update_xaxes(title="Longitude")
    fig.update_layout(title_text=f"This week: {m['focus_river']} counties by 4-week tier")
    save_chart(fig, "this_week_map.html", status)


# ---------------------------------------------------------------------------
# Put it all together
# ---------------------------------------------------------------------------
def export():
    pred, outlook, latest, metrics, source, problems = load()
    status = status_of(source, metrics)
    write_text(OUT_DIR / "numbers.md", numbers_md(metrics, status))
    write_text(OUT_DIR / "writeup.md", writeup_md(metrics, status))
    write_text(OUT_DIR / "explain.md", explain_md(metrics, status))
    write_text(OUT_DIR / "story.md", story_md(pred, latest, metrics, status))
    build_charts(latest, metrics, status)
    return status


if __name__ == "__main__":
    print("pitch kit written to app/pitch_kit/ -", STATUS_LINES[export()])
