"""
streamlit_app.py - the demo app (seven tabs).

How it works, in plain English:
  * It gets ALL its data from app/contract.py -> load(). Nothing else. No internet.
  * It never works out a reported result. Every number about how good the system is
    comes straight out of metrics.json.
  * Tabs so far:  "This week" (today's forecast), "Replay" (step through a past year),
                  "Outlook check" (past 6/12-month outlooks vs what happened),
                  "Farm brief" (plain-English page to download),
                  "Other rivers and misses" (heat-maps of a whole river, plus the alarm's mistakes),
                  "How good is it" (the honest scorecard).
Run it with:  streamlit run app/streamlit_app.py
"""
import html
import sys
from pathlib import Path

# Let "from app.contract import ..." work when Streamlit runs this file as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd                      # noqa: E402
import plotly.graph_objects as go        # noqa: E402
import streamlit as st                   # noqa: E402

import importlib                         # noqa: E402

from app import brief as _brief, canal, mapdata as _mapdata, tallies as _tallies, theme   # noqa: E402

# A web host can keep OLD copies of our helper files in memory after an update, while this main
# file is new. That mismatch crashes the page. Re-reading the helpers on each run avoids it
# (they are small, so it costs almost nothing).
for _module in (_brief, canal, _mapdata, _tallies, theme):
    importlib.reload(_module)

from app.brief import CLASS_WORDS, build_brief, md_escape, streak_sentence   # noqa: E402
from app.contract import has_map_fields, load, load_reference   # noqa: E402
from app.mapdata import load_canals, load_river_line   # noqa: E402
from app.tallies import (errors_table, reconcile, river_grid, tally,   # noqa: E402
                         weeks_error)

st.set_page_config(page_title="Rio Grande Farm Drought Outlook", layout="wide")
theme.apply_theme()                      # fonts, colors and spacing for the whole page (app/theme.py)

# ---------------------------------------------------------------------------
# Words and colors used on several screens
# ---------------------------------------------------------------------------
TIER_COLOR = theme.TIER_COLOR            # sage / ochre / clay, shared with the charts

# The alarms the Replay tab can show: our system first, then the simple baselines.
ALARM_CHOICES = {
    "Our system": "alarm_system",
    "Baseline: D2 or worse now (persistence)": "alarm_persistence",
    "Baseline: D1 or worse now": "alarm_d1_now",
    "Baseline: getting worse": "alarm_worsening",
    "Baseline: typical for the time of year": "alarm_calendar",
}


@st.cache_data
def get_data():
    """Load the four files once and remember them (so the app stays fast)."""
    return load()


@st.cache_data
def get_river_line(river):
    """The river's line for the map (from the app's own small file)."""
    return load_river_line(river)


@st.cache_resource
def get_canals():
    """The pipeline's canal lines, grouped by county. Big file (about 8 MB), so read once and keep."""
    return load_canals()


@st.cache_data
def get_reference():
    """District table and cost figures for the Canal action tab (fixed files in app/reference/)."""
    return load_reference()


pred, outlook, latest, metrics, source, problems = get_data()
# The pipeline's extra map columns (overall level, ranges, drought history, feed cost) - if present.
map_fields = has_map_fields(latest)

# ---------------------------------------------------------------------------
# Top of the page: the hero banner, then banners that tell the viewer how much to trust the data
# ---------------------------------------------------------------------------
STATUS_CHIP = {"demo": "Demo data", "provisional": "Provisional results", "final": "Final results"}
status_key = "demo" if source == "demo" else ("final" if metrics["is_final"] else "provisional")
theme.hero(
    title="Rio Grande Farm Drought Outlook",
    kicker="AI + Climate  -  Veritas AI Hackathon",
    subtitle=(f"A 4-week alert, a 6-month outlook and a 12-month outlook for severe drought in "
              f"{metrics['n_focus_counties']} farm counties along the {metrics['focus_river']}, "
              "then a test of the same method on four other rivers."),
    chips=[STATUS_CHIP[status_key], f"Week of {latest['date'].max():%B %d, %Y}",
           f"{metrics['n_focus_counties']} counties"])

if source == "demo":
    st.error("DEMO DATA - not real results")
if problems:
    st.error("The real data files have problems, so demo data is shown instead:\n\n"
             + "\n".join(f"- {p}" for p in problems))
elif source == "real" and not metrics["is_final"]:
    st.warning("Provisional results")

# ---------------------------------------------------------------------------
# Sidebar: choose a river, then a county on that river
# ---------------------------------------------------------------------------
focus = metrics["focus_river"]
others = sorted(r for r in latest["river"].unique() if r != focus)
# Links can open the app on one river, county and tab (?river=Ohio&fips=39900&view=Replay).
# We read the address ONCE per visit, validate it, and use it as the starting choice.
TAB_NAMES = ["This week", "Canal action", "Replay", "Outlook check", "Farm brief",
             "Other rivers and misses", "How good is it"]
if "url_read" not in st.session_state:
    st.session_state["url_read"] = True
    q = st.query_params
    if q.get("river") in [focus] + others:                  # ignore anything that isn't a real river
        st.session_state["river"] = q["river"]
    match = latest[latest["fips"] == q.get("fips", "")]     # ignore an unknown county code
    if not match.empty:
        st.session_state["river"] = match.iloc[0]["river"]  # a county's own river wins
        st.session_state["fips"] = match.iloc[0]["fips"]
    st.session_state["start_tab"] = q.get("view") if q.get("view") in TAB_NAMES else None

theme.sidebar_brand("Choose a place",
                    "The Rio Grande carries mountain snowmelt through Colorado, New Mexico and Texas "
                    "to the Gulf of Mexico.")
river = st.sidebar.selectbox(
    "River", [focus] + others, key="river",
    format_func=lambda r: r if r == focus else f"{r} (transfer test)")
st.sidebar.caption(f"Transfer test rivers (model trained on the {focus}): " + ", ".join(others))

river_latest = latest[latest["river"] == river]
names = {r.fips: f"{r.county}, {r.state}" for r in river_latest.itertuples()}   # fips -> label
fips_options = sorted(names, key=names.get)                                     # sorted by name
# If the river just changed, a county from the old river is no longer valid: pick the first one.
if st.session_state.get("fips") not in fips_options and "fips" in st.session_state:
    st.session_state["fips"] = fips_options[0]
fips = st.sidebar.selectbox("County", fips_options, format_func=names.get, key="fips")
county_label = names[fips]
is_transfer = river != focus

# Sidebar "Data checks": re-count the alarms in the app and compare with metrics.json.
# If they disagree, the files are suspect. We never patch them - we tell the Pipeline owner.
with st.sidebar.expander("What do these words mean?"):
    st.markdown(
        "- **Severe drought (D2 or worse):** a level on the U.S. Drought Monitor map, drawn weekly.\n"
        "- **Low / Watch / Warning:** how worried to be. Warning means the forecast has crossed its tested threshold.\n"
        "- **6-month chance:** the chance of 8 straight weeks of severe drought in the next 6 months.\n"
        "- **Inspect first:** a canal on leaky soil in a county the forecast warns about.\n"
        "- **Estimate:** worked out from published figures. Not a prediction, not a measurement.")
st.sidebar.markdown("#### Data checks")
mismatches = reconcile(pred, metrics)
if mismatches:
    st.sidebar.warning("App counts do not match metrics.json:\n\n" + "\n".join(f"- {md_escape(m)}" for m in mismatches)
                       + "\n\nTell the Pipeline owner. Do not edit the files.")
else:
    st.sidebar.success("App counts match metrics.json")


def pick_county_from_map():
    """Runs when a dot on the map is clicked: make that county the selected one."""
    points = st.session_state.get("risk_map", {}).get("selection", {}).get("points", [])
    if points:
        clicked = str(points[0].get("customdata", [""])[0])
        if clicked in set(latest["fips"]):          # only accept a real county code
            st.session_state["fips"] = clicked


def transfer_note():
    """Grey note shown at the top of every tab when a non-focus river is picked."""
    if is_transfer:
        st.caption("This river was not used to train the model.")


# ---------------------------------------------------------------------------
# TAB 1: This week
# ---------------------------------------------------------------------------
def tab_this_week():
    transfer_note()
    row = latest[latest["fips"] == fips].iloc[0]
    st.subheader(f"{md_escape(county_label)} - week of {row['date']:%B %d, %Y}")

    # The answer first, in plain words: what to do, from the 6-month chance (same rule as the Canal action tab).
    tier, why = canal.action_tier(canal.county_probability(row)[0])
    theme.callout(f"What to do now: {tier}. {why} Open the Canal action tab for your canals and the sealant plan.")

    # Three cards: the 4-week alert, the 6-month outlook, the 12-month outlook.
    theme.card_grid([
        dict(label="Next 4 weeks", value=row["tier"], dot=True, accent=TIER_COLOR[row["tier"]],
             caption=f"Risk score {round(row['p_model'] * 100)}%. A risk score, not a calibrated probability.",
             rows=[f"Drought now: {CLASS_WORDS[int(row['cls'])]}"]),
        dict(label="Next 6 months", value=f"{round(row['p_season'] * 100)}%",
             accent=TIER_COLOR[row["season_tier"]],
             caption="chance of 8 straight weeks of severe drought",
             rows=[f"Level: {row['season_tier']}"]),
        dict(label="Next 12 months", value=f"about {round(row['weeks_model'])} weeks", accent=theme.CHART_COLORS[0],
             caption="of severe drought",
             rows=([f"Likely range: {round(row['weeks_low'])} to {round(row['weeks_high'])} weeks"] if map_fields else [])
                  + [f"Usual for this county: {round(row['weeks_usual'])} weeks",
                     f"Typical error: about {metrics['year']['focus']['mae_system']} weeks"]),
    ])

    # Past drought spells and an illustrative feed-cost estimate (the pipeline's map fields).
    # The feed-cost numbers are UNTESTED estimates, and we say so on the card and under it.
    if map_fields:
        mf = metrics["map_fields"]
        typical = round(row["typical_drought_weeks"])
        theme.card_grid([
            dict(label="Past severe-drought spells", value=f"{round(row['longest_drought_weeks'])} weeks",
                 accent=TIER_COLOR["Watch"], caption="longest spell on record for this county",
                 rows=[f"Typical spell: {typical} weeks" if typical else "No severe-drought spell on record"]),
            dict(label="Feed cost estimate (untested)", value=f"${round(row['damage_usd_per_100_head']):,}",
                 accent=TIER_COLOR["Warning"], caption="per 100 cattle, illustrative only",
                 rows=[f"About {row['damage_months']:.1f} months of bought feed",
                       f"Assumes ${mf['feed_cost_per_head_month']} per head per month"]),
        ])
        # The pipeline's own sentence, with its column name swapped for plain words.
        tested = mf["tested"].replace("risk_level", "the overall level")
        tested = tested[0].upper() + tested[1:]            # the pipeline's sentence now starts a line
        st.caption(md_escape(f"{tested} Feed price: {mf['feed_cost_source']}. This is not a prediction "
                             "of losses, not a payment, and not financial advice."))

    # The link to the USDA program, in careful words (we never predict a payment).
    note = streak_sentence(int(row["d2_streak"]))    # wording shared with the Farm brief
    if note:
        theme.callout(note)
    st.caption("This is a forecast tool, not a payment decision.")

    # A real map: scroll to zoom, drag to move, hover for the forecasts, click a county to select it.
    st.markdown("#### Where the risk is")
    st.caption("Scroll to zoom, drag to move, click a county to select it. "
               + ("Dot color = the worse of the 4-week and 6-month levels." if map_fields else ""))
    level_col = "risk_level" if map_fields else "tier"      # overall level when the pipeline gives it
    st.plotly_chart(theme.risk_map(river_latest, fips, river_lines=get_river_line(river), river_name=river,
                                   level_col=level_col),
                    key="risk_map", on_select=pick_county_from_map,
                    selection_mode="points", config={"scrollZoom": True}, width="stretch")

    # Two small tables under the map: the counties on Warning, then the ones on Watch.
    cols = st.columns(2, gap="large")
    for col, (tier, note) in zip(cols, (("Warning", "Review stocking, feed and water plans."),
                                        ("Watch", "Keep an eye on hay and water plans."))):
        with col:
            st.markdown(f"#### Counties on {tier}")
            hot = river_latest[river_latest["tier"] == tier].sort_values("p_model", ascending=False)
            if hot.empty:
                st.write(f"No counties on {tier} this week.")
            else:
                st.caption(note)
                table = pd.DataFrame({"County": hot["county"], "State": hot["state"],
                                      "4-week risk %": (hot["p_model"] * 100).round(),
                                      "6-month %": (hot["p_season"] * 100).round(),
                                      "12-month weeks": hot["weeks_model"].round()})
                st.dataframe(table, hide_index=True, width="stretch")


# ---------------------------------------------------------------------------
# TAB 2: Replay - step through a past year and see what the alarm said
# ---------------------------------------------------------------------------
def step_week(key, delta, last):
    """Button callback: move the week slider by delta weeks, staying inside the year."""
    st.session_state[key] = max(0, min(last, st.session_state[key] + delta))


def tab_replay():
    transfer_note()
    st.caption("Pick a past week and see what our alert said then, and what really happened in the next 4 weeks.")
    hist = pred[pred["fips"] == fips]
    if hist.empty:
        st.info("No replay data for this county.")
        return

    # Pick a year. Default: the year with the most severe-drought weeks for this county.
    years = sorted(hist["date"].dt.year.unique())
    worst = hist.groupby(hist["date"].dt.year)["y"].sum().idxmax()
    pick_year, pick_alarm = st.columns(2)
    year = pick_year.selectbox("Year", years, index=years.index(worst), key=f"year_{fips}")
    wk = hist[hist["date"].dt.year == year].reset_index(drop=True)
    last = len(wk) - 1

    alarm_name = pick_alarm.selectbox("Which alarm to show", list(ALARM_CHOICES))
    alarm_col = ALARM_CHOICES[alarm_name]

    # Week slider plus step buttons. The chosen week lives in session_state.
    key = f"week_{fips}_{year}"
    if key not in st.session_state:
        # Start 12 weeks into the year, or at the first alarm if that comes later, so the chart
        # already has some history on screen when the viewer arrives.
        fired = wk.index[wk[alarm_col]]           # weeks when the chosen alarm went off
        st.session_state[key] = min(last, max(int(fired[0]) if len(fired) else 0, 12))
    b = st.columns(4)
    b[0].button("Back 4 weeks", on_click=step_week, args=(key, -4, last), width="stretch")
    b[1].button("Previous week", on_click=step_week, args=(key, -1, last), width="stretch")
    b[2].button("Next week", on_click=step_week, args=(key, 1, last), width="stretch")
    b[3].button("Forward 4 weeks", on_click=step_week, args=(key, 4, last), width="stretch")
    idx = st.select_slider("Week", options=list(range(last + 1)), key=key,
                           format_func=lambda i: f"{wk['date'][i]:%b %d, %Y}")
    chosen_date = wk["date"][idx]

    # By default we hide the future. The toggle reveals the 4 weeks after the chosen week.
    reveal = st.toggle("Reveal the next 4 weeks")
    shown = wk.iloc[: min(idx + (4 if reveal else 0), last) + 1]
    alarms = wk.iloc[: idx + 1]
    alarms = alarms[alarms[alarm_col]]                       # alarm weeks up to the chosen week

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=shown["date"], y=shown["cls"], mode="lines", line_shape="hv",
                             name="Drought class", line=dict(color=theme.CHART_COLORS[0], width=3)))
    fig.add_trace(go.Scatter(x=alarms["date"], y=alarms["cls"], mode="markers", name="Alarm",
                             marker=dict(size=12, color=TIER_COLOR["Warning"], symbol="triangle-up")))
    fig.add_hline(y=3, line_dash="dash", line_color=TIER_COLOR["Watch"],
                  annotation_text="D2 severe", annotation_position="top left")
    fig.add_shape(type="line", x0=chosen_date, x1=chosen_date, y0=-0.2, y1=5.2,
                  line=dict(color=theme.palette()["heading"], width=2))
    fig.update_xaxes(range=[wk["date"].min(), wk["date"].max()])
    fig.update_yaxes(range=[-0.2, 5.2], tickvals=list(CLASS_WORDS), ticktext=list(CLASS_WORDS.values()))
    fig.update_layout(margin=dict(l=10, r=10, t=30, b=10))
    st.plotly_chart(theme.style_fig(fig, 400), width="stretch")

    # Alert log. We only say what happened next if 4 full weeks have passed since the alarm.
    st.markdown("#### Alert log")
    if alarms.empty:
        st.write("No alarms up to this week.")
    else:
        def outcome(r):
            if r["date"] > chosen_date - pd.Timedelta(weeks=4):
                return "too recent to know"
            return "severe drought followed within 4 weeks" if r["y"] == 1 else "no severe drought followed"
        log = pd.DataFrame({"Week": alarms["date"].dt.strftime("%b %d, %Y"),
                            "Drought class": alarms["cls"].map(CLASS_WORDS),
                            "What happened in the next 4 weeks": alarms.apply(outcome, axis=1)})
        st.dataframe(log, hide_index=True, width="stretch")


# ---------------------------------------------------------------------------
# TAB 3: How good is it - every number here comes straight from metrics.json
# ---------------------------------------------------------------------------
def show_failures():
    """List the failure examples written by the pipeline (used on two tabs)."""
    for f in metrics["failure_examples"]:
        st.write(f"- **{md_escape(f['product'])}**, {md_escape(f['date'])}, {md_escape(f['county'])}, "
                 f"{md_escape(f['state'])}: {md_escape(f['what_happened'])}")


def yes_no(flag):
    """True/False as plain words."""
    return "yes" if flag else "no"


def kv_table(d):
    """Turn the single values of a dict into a two-column table."""
    rows = [(k.replace("_", " "), str(v)) for k, v in d.items() if not isinstance(v, (dict, list))]
    return pd.DataFrame(rows, columns=["Measure", "Value"])


def colored(df, good):
    """Green row when `good` is True, red when False. Used for the other-rivers tables."""
    def paint(row):
        color = "#dfead9" if good.loc[row.name] else "#f0d9d0"      # soft sage / soft clay
        return [f"background-color: {color}; color: #111"] * len(row)
    return df.style.apply(paint, axis=1)


def tab_how_good():
    transfer_note()
    st.caption("How well the forecasts did on years they had not seen, next to simple rules. Weak results are shown too.")
    m = metrics

    # 1) The 4-week alert.
    st.header(f"4-week alert on the {focus}")
    st.caption(f"Cost = {m['miss_cost']} x missed droughts + false alarms. That cost rule is our "
               "assumption, not a farmer's number. Lower is better.")
    pol = pd.DataFrame(m["policies"]).rename(columns={
        "name": "Rule", "cost": "Cost", "precision": "Precision", "recall": "Recall",
        "alarms": "Alarms", "caught": "Caught", "missed": "Missed",
        "false_alarms": "False alarms", "auc": "AUC"}).drop(columns=["column"])
    st.dataframe(pol, hide_index=True, width="stretch")

    h = m["headline"]
    verdict = "PASSED" if h["honesty_check_pass"] else "FAILED"
    # Three big numbers first, then the details. All values come straight from metrics.json.
    theme.card_grid([
        dict(label="Our system's cost", value=str(h["system_cost"]), accent=theme.CHART_COLORS[1],
             caption=f"against {h['persistence_cost']} for 'the future equals today'"),
        dict(label="Cheaper than that rule", value=f"{h['pct_cheaper_than_persistence']}%",
             accent=theme.CHART_COLORS[0],
             caption=f"best simple rule: {h['cheapest_baseline_on_test']} at {h['cheapest_baseline_cost']}"),
        dict(label="Honesty check", value=verdict.capitalize(),
             accent=TIER_COLOR["Low"] if h["honesty_check_pass"] else TIER_COLOR["Warning"],
             caption="beats every simple rule on years it never saw"),
    ])
    st.markdown("**Hard part: counties not yet in severe drought (onset)**")
    st.dataframe(kv_table(m["onset"]), hide_index=True)
    ev = m["events"]
    st.write(f"{ev['n']} times a county entered severe drought; {ev['warned_within_4_weeks']} had a "
             f"warning in the 4 weeks before (typical lead: {ev['median_lead_weeks']} weeks).")
    st.markdown("**Year by year**")
    st.dataframe(pd.DataFrame(m["year_by_year"]), hide_index=True)

    # 2) The 6-month outlook.
    sf = m["season"]["focus"]
    st.header("6-month outlook")
    st.caption(md_escape(m["season"]["target"]))
    st.dataframe(kv_table(sf), hide_index=True)
    st.write(f"Beats every baseline: **{yes_no(sf['beats_every_baseline'])}**")

    # 3) The 12-month outlook.
    yf = m["year"]["focus"]
    st.header("12-month outlook")
    st.caption(md_escape(m["year"]["target"]) + ". Errors are in weeks; lower is better.")
    st.dataframe(kv_table(yf), hide_index=True)
    st.write(f"Beats every baseline: **{yes_no(yf['beats_every_baseline'])}**")
    bars = {"Our system": yf["mae_system"], "Same as now": yf["mae_same_as_now"],
            "Same as last year": yf["mae_last_year"], "Usual for the county": yf["mae_usual"]}
    bar_fig = go.Figure(go.Bar(x=list(bars), y=list(bars.values()),
                               marker_color=[theme.CHART_COLORS[1]] + ["#b9b49f"] * 3))   # ours in green
    bar_fig.update_layout(yaxis_title="Average error (weeks)", margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(theme.style_fig(bar_fig, 320), width="stretch")

    # 4) Other rivers: green row = the system beats that river's best simple rule.
    st.header("Does it work on other rivers?")
    st.caption(f"Green = beats that river's best simple rule. Red = does not. "
               f"The model was trained on the {focus} only.")
    st.markdown("**4-week alert**")
    t = pd.DataFrame(m["per_river"])
    st.dataframe(colored(t, t["system_cost"] < t["best_rule_cost"]), hide_index=True)
    st.markdown("**6-month outlook**")
    t = pd.DataFrame(m["season"]["per_river"])
    st.dataframe(colored(t, t["system_cost"] < t["best_rule_cost"]), hide_index=True)
    st.markdown("**12-month outlook**")
    t = pd.DataFrame(m["year"]["per_river"])
    st.dataframe(colored(t, t["mae_system"] < t["mae_best_baseline"]), hide_index=True)

    # 5) Where it fails.
    st.header("Where it fails")
    show_failures()

    # 6) Extra checks and the plain list of limits.
    st.header("Extra checks and limits")
    st.dataframe(pd.DataFrame(m["ablations"]), hide_index=True, width="stretch")
    fi = pd.DataFrame(m["feature_importance"])
    fi_fig = go.Figure(go.Bar(x=fi["importance"], y=fi["feature"], orientation="h",
                              marker_color=theme.CHART_COLORS[0]))
    fi_fig.update_layout(xaxis_title="Importance", margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(theme.style_fig(fi_fig, 320), width="stretch")
    for sentence in m["limits"]:
        st.write(f"- {md_escape(sentence)}")

    # 7) The canal-pivot results. Each block is optional: if the pipeline did not write it, say so.
    show_trigger(m.get("trigger"))
    show_losses(m.get("losses"))
    show_reservoirs(m.get("reservoir"))


# Names of the lines in trigger.value_sweep -> plain words for the chart legend.
SWEEP_NAMES = {"forecast": "Our forecast", "forecast_reservoir": "Our forecast with reservoirs",
               "d1_rule": "D1 or worse now", "persistence": "D2 or worse now",
               "seal_every_year": "Seal every year"}


def show_trigger(trig):
    """Does the forecast work as a pre-season trigger? Everything comes from metrics.json."""
    st.header("Does the forecast work as a pre-season trigger?")
    if not isinstance(trig, dict):
        st.write("Not available yet.")
        return
    months = ", ".join(str(x) for x in trig["issue_months"])
    st.caption(f"Scored on {trig['rows']} Rio Grande rows issued in months {months} of the test years, "
               f"with {trig['drought_seasons']} drought seasons. A rule fires when its chance is at least "
               f"{round(trig['threshold'] * 100)}%.")
    st.dataframe(pd.DataFrame(trig["rules"]), hide_index=True, width="stretch")
    if trig["value_sweep"]:
        sweep = pd.DataFrame(trig["value_sweep"])
        fig = go.Figure()
        for col, name in SWEEP_NAMES.items():
            if col in sweep.columns:
                fig.add_trace(go.Scatter(x=sweep["cost_ratio"], y=sweep[col], mode="lines+markers", name=name))
        fig.update_layout(xaxis_title="Cost of acting, as a share of the loss avoided",
                          yaxis_title="Value per row (higher is better)")
        st.plotly_chart(theme.style_fig(fig, 340), width="stretch")
    if trig["value_sweep"]:
        for sentence in canal.trigger_verdict(trig):
            st.write(sentence)
    st.caption("The file's own yes/no flags: forecast beats the D1 rule = "
               f"{yes_no(trig['forecast_beats_d1_rule'])}; with reservoirs = "
               f"{yes_no(trig['reservoir_forecast_beats_d1_rule'])}. The flag counts any margin, however small, "
               "so we word the result from the scores above.")


def show_losses(loss):
    """Measured drought losses from the insurance files. If the lists are empty, only the note shows."""
    st.header("Measured drought losses")
    if not isinstance(loss, dict):
        st.write("Not available yet.")
        return
    if loss["by_year"] or loss["by_county"]:
        st.metric(f"Insured drought losses, {loss['years'][0]} to {loss['years'][1]}", f"${loss['total_usd']:,.0f}")
        if loss["by_year"]:
            by_year = pd.DataFrame(loss["by_year"])
            fig = go.Figure(go.Bar(x=by_year["year"], y=by_year["usd"], marker_color=theme.CHART_COLORS[0]))
            fig.update_layout(xaxis_title="Year", yaxis_title="Insured loss (US dollars)")
            st.plotly_chart(theme.style_fig(fig, 300), width="stretch")
        if loss["by_county"]:
            st.dataframe(pd.DataFrame(loss["by_county"]), hide_index=True, width="stretch")
        st.caption(md_escape(f"Source: {loss['source']}."))
    st.caption(md_escape(loss["note"]))


def show_reservoirs(res):
    """Which reservoirs the pipeline matched to counties."""
    st.header("Reservoirs")
    if not isinstance(res, dict):
        st.write("Not available yet.")
        return
    if res["systems"]:
        st.dataframe(pd.DataFrame(res["systems"]), hide_index=True, width="stretch")
    st.caption(md_escape(f"{res['counties_without_reservoir']} counties have no matched reservoir. {res['note']}"))


# ---------------------------------------------------------------------------
# TAB: Outlook check - every past 6- and 12-month outlook next to what really happened
# ---------------------------------------------------------------------------
COUNT_NOTE = "counted in the app for this one county, not a reported result"


def tab_outlook_check():
    transfer_note()
    st.caption("Every point was predicted by a model trained only on earlier years.")
    o = outlook[outlook["fips"] == fips].sort_values("date")
    if o.empty:
        st.info("No outlook history for this county.")
        return
    month = 28 * 24 * 3600 * 1000            # bar width in milliseconds (about one month)

    # Chart A: the 6-month risk over time. Red bands = it really did get 8 straight bad weeks.
    st.markdown("#### 6-month outlook, checked")
    hit = o[o["y_season"] == 1]
    figa = go.Figure()
    figa.add_trace(go.Bar(x=hit["date"], y=[1] * len(hit), width=month, name="8 straight weeks really followed",
                          marker=dict(color=TIER_COLOR["Warning"], opacity=0.25)))
    figa.add_trace(go.Scatter(x=o["date"], y=o["p_season"], mode="lines", name="6-month risk",
                              line=dict(color=theme.CHART_COLORS[1], width=2.5)))
    figa.add_hline(y=metrics["season"]["threshold"], line_dash="dash", line_color=TIER_COLOR["Watch"],
                   annotation_text="alarm line", annotation_position="top left")
    figa.update_yaxes(range=[0, 1], title="Risk")
    figa.update_layout(margin=dict(l=10, r=10, t=30, b=10))
    st.plotly_chart(theme.style_fig(figa, 350), width="stretch")
    st.caption("Shaded = the next 6 months really did contain 8 straight weeks of severe drought.")
    t = tally(o, "alarm_season", "y_season", metrics["miss_cost"])
    st.caption(f"This county: {t['alarms']} alarms, {t['caught']} caught, {t['missed']} missed, "
               f"{t['false_alarms']} false alarms (cost {t['cost']}) - {COUNT_NOTE}.")

    # Chart B: the 12-month weeks estimate against the real number of weeks (bars).
    st.markdown("#### 12-month outlook, checked")
    figb = go.Figure()
    figb.add_trace(go.Bar(x=o["date"], y=o["y_weeks"], width=month, name="Weeks that really happened",
                          marker=dict(color="#e2d8bd")))
    for col, name in [("weeks_model", "Our estimate"), ("weeks_usual", "Usual for this county"),
                      ("weeks_same_as_now", "Same as now")]:
        figb.add_trace(go.Scatter(x=o["date"], y=o[col], mode="lines", name=name))
    figb.update_yaxes(title="Weeks of severe drought (next 52)")
    figb.update_layout(margin=dict(l=10, r=10, t=30, b=10))
    st.plotly_chart(theme.style_fig(figb, 350), width="stretch")
    st.caption(f"Average error for this county: ours {weeks_error(o, 'weeks_model'):.1f} weeks, "
               f"usual {weeks_error(o, 'weeks_usual'):.1f}, same as now {weeks_error(o, 'weeks_same_as_now'):.1f} "
               f"- {COUNT_NOTE}.")


# ---------------------------------------------------------------------------
# TAB: Farm brief - a plain-English page for one county, with a download button
# ---------------------------------------------------------------------------
def tab_farm_brief():
    transfer_note()
    st.caption("A short plain-English summary for this county that you can read or download.")
    status = "DEMO" if source == "demo" else ("FINAL" if metrics["is_final"] else "PROVISIONAL")
    row = latest[latest["fips"] == fips].iloc[0]
    brief = build_brief(row, pred[pred["fips"] == fips], metrics, status)
    st.markdown(brief)
    st.download_button("Download this brief (.md)", brief, file_name=f"farm_brief_{fips}.md",
                       mime="text/markdown")


# ---------------------------------------------------------------------------
# TAB: Other rivers and misses - a whole river for one year, plus the alarm's mistakes
# ---------------------------------------------------------------------------
COUNT_LABEL = "counted in the app, not a reported result"


def heat(matrix, title, scale, zmax, ticks):
    """One county-by-week heat-map. `ticks` maps color-bar numbers to words."""
    fig = go.Figure(go.Heatmap(
        z=matrix.values, x=matrix.columns, y=list(matrix.index), colorscale=scale, zmin=0, zmax=zmax,
        colorbar=dict(tickvals=list(ticks), ticktext=list(ticks.values()))))
    fig.update_yaxes(autorange="reversed")                 # first county (northernmost) at the top
    fig.update_layout(title=title, margin=dict(l=10, r=10, t=40, b=10))
    return theme.style_fig(fig, 120 + 28 * len(matrix))


def tab_other_rivers():
    transfer_note()
    st.caption("The same method tried on other rivers, with the misses and false alarms. This is a test, not a product.")
    mine = pred[pred["river"] == river]
    years = sorted(mine["date"].dt.year.unique())
    worst = mine.groupby(mine["date"].dt.year)["y"].sum().idxmax()      # year with the most droughts
    year = st.selectbox("Year", years, index=years.index(worst), key=f"rivers_year_{river}")

    # Two heat-maps side by side in time: what our alert said, then what really happened.
    tiers, cls = river_grid(pred, river, year)
    # Three flat colors (no gradient): each tier fills a third of the color bar.
    steps = [[0, TIER_COLOR["Low"]], [1 / 3, TIER_COLOR["Low"]], [1 / 3, TIER_COLOR["Watch"]],
             [2 / 3, TIER_COLOR["Watch"]], [2 / 3, TIER_COLOR["Warning"]], [1, TIER_COLOR["Warning"]]]
    st.plotly_chart(heat(tiers, f"Our alert - {river}, {year}", steps, 2,
                         {1 / 3: "Low", 1: "Watch", 5 / 3: "Warning"}), width="stretch")
    st.plotly_chart(heat(cls, f"Actual drought class - {river}, {year}", theme.DROUGHT_SCALE, 5, CLASS_WORDS),
                    width="stretch")
    st.caption("Counties run north (top) to south (bottom). Compare the two maps: "
               "red in the lower one with grey in the upper one is a miss.")

    # The mistakes of one alarm for this river and year.
    st.markdown("#### Misses and false alarms")
    policy = st.selectbox("Which alarm", [p["name"] for p in metrics["policies"]])
    col = next(p["column"] for p in metrics["policies"] if p["name"] == policy)
    missed, false_alarms = errors_table(mine[mine["date"].dt.year == year], col)
    st.caption(f"{river}, {year} - {COUNT_LABEL}.")
    for title, table in (("Missed (no alarm, severe drought followed)", missed),
                         ("False alarms (alarm, no severe drought followed)", false_alarms)):
        st.markdown(f"**{title}: {len(table)}**")
        if not table.empty:
            shown = table.assign(date=table["date"].dt.strftime("%b %d, %Y"),
                                 cls=table["cls"].map(CLASS_WORDS),
                                 p_model=(table["p_model"] * 100).round().astype(int).astype(str) + "%")
            st.dataframe(shown.rename(columns={"date": "Week", "county": "County", "state": "State",
                                               "river": "River", "cls": "Drought class",
                                               "p_model": "Risk score"}),
                         hide_index=True, width="stretch")

    st.markdown("#### Failure examples (from the pipeline)")
    show_failures()


def show_canal_map(fips):
    """Canal lines for the chosen county, colored by the pipeline's level. Needs the pipeline's file."""
    prio = metrics.get("canal_priority")
    canals = get_canals() if isinstance(prio, dict) else {}
    if not canals:
        st.write("Canal map: not available yet.")
        return
    segs = canals.get(fips, [])
    if not segs:
        st.info("No canal lines for this county in the pipeline's file.")
        return
    km = {lvl: sum(x["length_km"] or 0 for x in segs if x["level"] == lvl) for lvl in theme.CANAL_COLOR}
    # One plain sentence first, so the manager knows what to look for on the map.
    inspect = km["Inspect first"]
    if inspect >= 0.5:
        st.markdown(f"**{inspect:,.0f} km of the {sum(km.values()):,.0f} km of canal in this county are marked "
                    "'Inspect first'** (red). Those sit on leaky soil in a county the forecast warns about.")
    else:
        st.markdown(f"**No canal in this county is marked 'Inspect first' this week** "
                    f"({sum(km.values()):,.0f} km mapped). That level needs leaky soil AND a forecast warning.")
    st.plotly_chart(theme.canal_map(segs), width="stretch", key="canal_map")
    st.caption(md_escape("Kilometres by level: " + ", ".join(f"{lvl} {v:,.0f}" for lvl, v in km.items() if v)
                         + ". Click a level in the legend to hide or show it; scroll to zoom."))
    # Named canals to inspect first: this county's, or the top few across all counties.
    named = pd.DataFrame(prio["named"])
    mine = named[named["county"] == names[fips].split(",")[0]] if not named.empty else named
    if not mine.empty:
        st.markdown("**Named canals to inspect first in this county**")
        st.dataframe(mine.head(10).rename(columns={
            "name": "Canal", "county": "County", "state": "State", "inspect_first_km": "Inspect-first km",
            "seepage_rate": "Seepage (gal/sq ft/day)", "p_season": "6-month chance"}),
            hide_index=True, width="stretch")
    with st.expander("How the levels are set"):
        st.write(md_escape(prio["rule"]) if "rule" in prio else "")
    st.caption(md_escape(prio["note"]))
    st.caption(canal.ESTIMATE_LABEL)


def show_district_plan(fips):
    """The pipeline's sealant plan: which Texas districts get the budget, and how much water it might save."""
    plan = metrics.get("districts")
    if not isinstance(plan, dict):
        st.write("District plan: not available yet.")
        return
    county = names[fips].split(",")[0]
    mine = canal.districts_in_county(plan, county) if row_state(fips) == "Texas" else []
    if row_state(fips) != "Texas":
        st.info("The district plan covers Texas districts only: no public boundary file was found for "
                "New Mexico or Colorado districts.")
    elif not mine:
        st.info(f"No irrigation district in the plan covers {county} County.")
    else:
        st.markdown(f"**Districts that cover {county} County**")
        st.dataframe(pd.DataFrame({
            "District": [d["district"] for d in mine],
            "Risk": [d["risk"] for d in mine],
            "Canal km": [d["canal_km"] for d in mine],
            "Km sealed in the plan": [d["sealed_km"] for d in mine],
            "Sealant cost": [canal.usd(d["sealant_usd"]) for d in mine],
            "Water saved (acre-ft, a range)": [f"{d['saved_af_low']:,} to {d['saved_af_high']:,}" for d in mine],
            "First canals": [", ".join(d["first_canals"]) for d in mine],
        }), hide_index=True, width="stretch")

    # The whole picture: where the example budget goes, biggest first, colored by risk.
    top = sorted(plan["districts"], key=lambda d: d["sealant_usd"], reverse=True)[:10]
    fig = go.Figure(go.Bar(
        x=[d["sealant_usd"] for d in top][::-1], y=[d["district"] for d in top][::-1], orientation="h",
        marker_color=[TIER_COLOR[d["risk"]] for d in top][::-1],
        hovertemplate="%{y}<br>%{x:$,.0f}<extra></extra>"))
    fig.update_layout(xaxis_title=f"Sealant spend in the plan (US dollars, example budget {canal.usd(plan['budget_usd'])})",
                      margin=dict(l=10, r=10, t=10, b=10))
    st.markdown("**Where the example budget goes (top 10 districts)**")
    st.plotly_chart(theme.style_fig(fig, 380), width="stretch")
    st.caption(f"Bar color = the district's risk: green Low, ochre Watch, red Warning. In total the plan seals "
               f"{plan['sealed_km']:,.0f} km for {canal.usd(plan['spent_usd'])} and might save "
               f"{plan['saved_af_low']:,} to {plan['saved_af_high']:,} acre-feet. Sealing everything would cost "
               f"{canal.usd(plan['cost_to_treat_everything_usd'])}.")
    with st.expander("How the plan works"):
        st.write(md_escape(plan["rule"]))
    st.caption(md_escape(plan["note"]))
    st.caption(canal.ESTIMATE_LABEL)


def row_state(fips):
    """The state name of a county code (used to tell Texas counties from the others)."""
    return latest.loc[latest["fips"] == fips, "state"].iloc[0]


def tab_canal():
    """
    The "Canal action" tab, written for an irrigation district manager:
    1) what to do now, 2) which canals, 3) which districts get the budget, 4) size your own canal.
    The forecast is the AI part. Everything else is arithmetic on published figures (app/canal.py)
    or the pipeline's plan, so every output carries the estimate label.
    """
    st.subheader(f"Canal plan - {md_escape(county_label)}")
    districts, costs = get_reference()
    row = latest[latest["fips"] == fips].iloc[0]
    p, has_res = canal.county_probability(row)

    # 1) The answer first: one verdict, then the few facts behind it.
    tier, why = canal.action_tier(p)
    theme.callout(f"{tier}. {why}")
    st.caption("This is a proposal built from the forecast, not a tested result. "
               "Our AI forecasts drought; everything below turns that forecast into a canal plan with published figures.")
    cards = [dict(label="Chance of a severe drought season", value=f"{round(p * 100)}%", accent=theme.CHART_COLORS[0],
                  caption="8 straight weeks of severe drought in the next 6 months",
                  rows=["Same number as the This week tab" + (" (reservoir storage did not improve it)" if has_res else "")])]
    if "res_name" in latest.columns and row["res_name"] != "none":
        cards.append(dict(label="Reservoir", value=f"{round(row['res_pct_full'])}% full",
                          accent=theme.CHART_COLORS[0], caption=str(row["res_name"]),
                          rows=["Storage on the latest date"]))
    if "d2_share_history" in latest.columns:
        cards.append(dict(label="History since 2000", value=f"{round(row['d2_share_history'] * 100)}%",
                          accent=TIER_COLOR["Watch"], caption="of weeks in severe drought here"))
    theme.card_grid(cards)

    # The canal map and the district plan exist for the Rio Grande only. On a transfer-test river
    # we stop here and say so, instead of showing Rio Grande figures under another river's name.
    if is_transfer:
        st.info(f"The canal map and the sealant plan cover the {focus} counties only. "
                f"Pick {focus} in the sidebar to see them.")
        return

    # 2) Which canals? The map is what a district manager acts on.
    st.markdown("#### 1. Which canals to look at")
    show_canal_map(fips)

    # 3) Which districts get the money?
    st.markdown("#### 2. Where the sealant budget goes")
    show_district_plan(fips)

    # 4) The fixed "Read this first" box (the five lines the plan requires), always visible.
    trig = metrics.get("trigger")
    if isinstance(trig, dict) and trig.get("value_sweep"):
        d1 = " ".join(canal.trigger_verdict(trig))
    else:
        d1 = "How the forecast compared with the simple 'D1 or worse now' rule: not available yet."
    st.markdown("#### Read this first")
    st.markdown("\n".join(f"{i}. {line}" for i, line in enumerate([
        "The forecast is tested. The canal plan is a proposal built from published figures.",
        d1,
        "The sealant has not been field-tested on the Rio Grande. Results elsewhere ranged from no effect to a full stop of seepage.",
        "District figures are from 1998. Some canals have been lined since.",
        "Valley canals also carry city water. Any sealant would need the district's and regulators' approval.",
    ], start=1)))

    # 5) Extra detail, folded away so the page stays short.
    with st.expander("Older published figures: Texas A&M efficiency by district (1998)"):
        valley_p = canal.valley_probability(latest)
        if fips in canal.VALLEY_FIPS and valley_p is not None:
            ranked = canal.district_priority(districts, valley_p)
            st.dataframe(ranked.rename(columns={
                "district": "District", "efficiency_pct": "Efficiency %",
                "save80_low": "Recoverable at 80%, low (acre-ft)", "save80_high": "Recoverable at 80%, high (acre-ft)",
                "priority_low": "Priority, low", "priority_high": "Priority, high"}).round(0),
                hide_index=True, width="stretch")
            st.caption(f"Priority = the highest 6-month probability among Cameron, Hidalgo and Willacy "
                       f"({round(valley_p * 100)}%) times the water a district could recover by reaching 80% "
                       "efficiency. The report puts these districts in the three counties together without saying "
                       "which is in which, so the list is shown for all three. The figures are 28 years old.")
            st.caption(canal.ESTIMATE_LABEL)
        else:
            st.write("No public 1998 district table for this county. Use the calculator below.")
    with st.expander("Size a canal of your own (calculator)"):
        show_calculator(costs)


def show_calculator(costs):
    """Inputs for one canal -> seepage, sealant cost, water saved, and a cost-per-acre-foot comparison."""
    c1, c2, c3, c4 = st.columns(4)
    miles = c1.number_input("Miles of earthen canal", min_value=0.1, max_value=500.0, value=1.0, step=0.5)
    width = c2.number_input("Wetted width (feet)", min_value=1.0, max_value=200.0, value=20.0, step=1.0)
    soil = c3.selectbox("Soil type", list(costs["seepage_gal_sqft_day"]), index=len(costs["seepage_gal_sqft_day"]) - 1)
    days = c4.number_input("Days of flow per year", min_value=1, max_value=365, value=300, step=10)

    seep = canal.seepage_af_per_year(miles, width, costs["seepage_gal_sqft_day"][soil], days, costs["gallons_per_af"])
    cost = canal.sealant_cost_per_season(miles, width, days, costs)
    saved_low, saved_high = canal.water_saved_range(seep, costs)
    cpa_low, cpa_high = canal.cost_per_af_range(cost, saved_low, saved_high)
    apps = canal.applications_per_season(days, costs["sealant_months_effective"])
    theme.card_grid([
        dict(label="Seepage per year", value=f"{round(seep):,} acre-ft", accent=theme.CHART_COLORS[0],
             caption="water that leaks out of the canal"),
        dict(label="Sealant cost per season", value=f"${round(cost):,}", accent=TIER_COLOR["Watch"],
             caption=f"materials only, {apps} coats"),
        dict(label="Water saved", value=f"{round(saved_low):,} to {round(saved_high):,} acre-ft",
             accent=TIER_COLOR["Low"], caption="if it works as in trials elsewhere (28% to 87%)"),
        dict(label="Cost per acre-foot", value=f"${round(cpa_low):,} to ${round(cpa_high):,}",
             accent=TIER_COLOR["Warning"], caption="sealant, materials only"),
    ])
    st.caption(canal.ESTIMATE_LABEL)

    fallow_low, fallow_high = (v / costs["fallow_af_per_acre"] for v in
                               (costs["fallow_usd_per_acre_low"], costs["fallow_usd_per_acre_high"]))
    lin_low, lin_high = canal.lining_cost_per_af_range(miles, width, seep, costs)
    fig = go.Figure()
    for name, lo, hi in [("Sealant", cpa_low, cpa_high), ("Fallowing", fallow_low, fallow_high),
                         ("Concrete lining", lin_low, lin_high)]:
        fig.add_trace(go.Scatter(x=[lo, hi], y=[name, name], mode="lines+markers", name=name,
                                 line=dict(width=8), marker=dict(size=12),
                                 hovertemplate=f"{name}: $%{{x:,.0f}} per acre-foot<extra></extra>"))
    fig.update_xaxes(type="log", title="Cost per acre-foot (US dollars, log scale)")
    fig.update_layout(showlegend=False)
    st.plotly_chart(theme.style_fig(fig, 260), width="stretch")
    st.caption("Each bar runs from the low to the high estimate. Lining assumes it stops all seepage and "
               "lasts 50 years. Fallowing = paying for 3 acre-feet per acre left dry at $425 to $700 an acre. "
               + canal.ESTIMATE_LABEL)


# ---------------------------------------------------------------------------
# Put the tabs on the page
# ---------------------------------------------------------------------------
# The canal plan is second, because it is what an irrigation district manager acts on.
TAB_FUNCTIONS = {"This week": tab_this_week, "Canal action": tab_canal, "Replay": tab_replay,
                 "Outlook check": tab_outlook_check, "Farm brief": tab_farm_brief,
                 "Other rivers and misses": tab_other_rivers, "How good is it": tab_how_good}
tabs = st.tabs(TAB_NAMES, key="view", on_change="rerun", default=st.session_state["start_tab"])
for tab, name in zip(tabs, TAB_NAMES):
    with tab:
        TAB_FUNCTIONS[name]()

theme.footer("Drought data: U.S. Drought Monitor (NDMC, USDA, NOAA), county archive by the Montana "
             "Climate Office. ENSO index: NOAA Climate Prediction Center. River lines: Natural Earth. "
             "Map: OpenStreetMap contributors, CARTO.")

# Write the current choices back to the web address, so "copy link" shares exactly this view.
st.query_params["river"] = river
st.query_params["fips"] = fips
if st.session_state.get("view"):
    st.query_params["view"] = st.session_state["view"]
