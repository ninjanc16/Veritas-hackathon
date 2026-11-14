"""
streamlit_app.py - the demo app (Phase 2: three tabs).

How it works, in plain English:
  * It gets ALL its data from app/contract.py -> load(). Nothing else. No internet.
  * It never works out a reported result. Every number about how good the system is
    comes straight out of metrics.json.
  * Tabs so far:  "This week" (today's forecast), "Replay" (step through a past year),
                  "How good is it" (the honest scorecard).
Run it with:  streamlit run app/streamlit_app.py
"""
import sys
from pathlib import Path

# Let "from app.contract import ..." work when Streamlit runs this file as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd                      # noqa: E402
import plotly.graph_objects as go        # noqa: E402
import streamlit as st                   # noqa: E402

from app.contract import load            # noqa: E402

st.set_page_config(page_title="Rio Grande Farm Drought Outlook", layout="wide")

# ---------------------------------------------------------------------------
# Words and colors used on several screens
# ---------------------------------------------------------------------------
CLASS_WORDS = {0: "None", 1: "D0 Abnormally dry", 2: "D1 Moderate", 3: "D2 Severe",
               4: "D3 Extreme", 5: "D4 Exceptional"}
TIER_COLOR = {"Low": "#9e9e9e", "Watch": "#f5a623", "Warning": "#d62728"}   # grey / amber / red
TIER_TEXT = {"Low": "gray", "Watch": "orange", "Warning": "red"}            # Streamlit text colors

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


pred, outlook, latest, metrics, source, problems = get_data()

# ---------------------------------------------------------------------------
# Banners at the very top: tell the viewer how much to trust what they see
# ---------------------------------------------------------------------------
if source == "demo":
    st.error("DEMO DATA - not real results")
if problems:
    st.error("The real data files have problems, so demo data is shown instead:\n\n"
             + "\n".join(f"- {p}" for p in problems))
elif source == "real" and not metrics["is_final"]:
    st.warning("Provisional results")

st.title("Rio Grande Farm Drought Outlook")

# ---------------------------------------------------------------------------
# Sidebar: choose a river, then a county on that river
# ---------------------------------------------------------------------------
focus = metrics["focus_river"]
others = sorted(r for r in latest["river"].unique() if r != focus)
river = st.sidebar.selectbox(
    "River", [focus] + others,
    format_func=lambda r: r if r == focus else f"{r} (transfer test)")
st.sidebar.caption(f"Transfer test rivers (model trained on the {focus}): " + ", ".join(others))

river_latest = latest[latest["river"] == river]
labels = {f"{r.county}, {r.state}": r.fips for r in river_latest.itertuples()}
county_label = st.sidebar.selectbox("County", sorted(labels))
fips = labels[county_label]
is_transfer = river != focus


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
    st.subheader(f"{county_label} - week of {row['date']:%B %d, %Y}")

    # Three cards: the 4-week alert, the 6-month outlook, the 12-month outlook.
    c1, c2, c3 = st.columns(3)
    with c1.container(border=True):
        st.markdown("**Next 4 weeks**")
        st.markdown(f"## :{TIER_TEXT[row['tier']]}[{row['tier']}]")
        st.write(f"Risk score: **{round(row['p_model'] * 100)}%**")
        st.caption(f"Drought now: {CLASS_WORDS[int(row['cls'])]}. "
                   "A risk score, not a calibrated probability.")
    with c2.container(border=True):
        st.markdown("**Next 6 months**")
        st.markdown(f"## {round(row['p_season'] * 100)}%")
        st.caption("chance of 8 straight weeks of severe drought")
        st.markdown(f"Level: :{TIER_TEXT[row['season_tier']]}[**{row['season_tier']}**]")
    with c3.container(border=True):
        st.markdown("**Next 12 months**")
        st.markdown(f"## about {round(row['weeks_model'])} weeks")
        st.caption("of severe drought")
        st.write(f"Usual for this county: {round(row['weeks_usual'])} weeks")
        st.write(f"Typical error: about {metrics['year']['focus']['mae_system']} weeks")

    # The link to the USDA program, in careful words (we never predict a payment).
    streak = int(row["d2_streak"])
    if 1 <= streak <= 7:
        st.info(f"In severe drought for {streak} weeks in a row. USDA's Livestock Forage Disaster "
                "Program can open at 8 consecutive weeks during the grazing period. "
                "Check with your county FSA office.")
    elif streak >= 8:
        st.info("8 or more weeks in a row. Ask your county FSA office about the "
                "Livestock Forage Disaster Program.")
    st.caption("This is a forecast tool, not a payment decision.")

    # Map of the river's counties, colored by tier. No base map, so it works offline.
    st.markdown("#### Map")
    fig = go.Figure()
    for tier in TIER_COLOR:
        sub = river_latest[river_latest["tier"] == tier]
        hover = [f"{r.county}, {r.state}<br>4-week: {r.tier}<br>6-month: {round(r.p_season * 100)}%"
                 f"<br>12-month: about {round(r.weeks_model)} weeks" for r in sub.itertuples()]
        fig.add_trace(go.Scatter(x=sub["lon"], y=sub["lat"], mode="markers", name=tier,
                                 text=hover, hoverinfo="text",
                                 marker=dict(size=13, color=TIER_COLOR[tier])))
    fig.add_trace(go.Scatter(x=[row["lon"]], y=[row["lat"]], mode="markers", name="Selected county",
                             hoverinfo="skip",
                             marker=dict(size=26, symbol="circle-open", color="black", line=dict(width=3))))
    fig.update_yaxes(scaleanchor="x", scaleratio=1, title="Latitude")   # equal aspect = no stretching
    fig.update_xaxes(title="Longitude")
    fig.update_layout(height=450, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, width="stretch")

    # Table of counties on a Warning.
    st.markdown("#### Counties on Warning")
    warn = river_latest[river_latest["tier"] == "Warning"].sort_values("p_model", ascending=False)
    if warn.empty:
        st.write("No counties on Warning this week.")
    else:
        table = pd.DataFrame({"County": warn["county"], "State": warn["state"],
                              "4-week risk %": (warn["p_model"] * 100).round(),
                              "6-month %": (warn["p_season"] * 100).round(),
                              "12-month weeks": warn["weeks_model"].round()})
        st.dataframe(table, hide_index=True, width="stretch")


# ---------------------------------------------------------------------------
# TAB 2: Replay - step through a past year and see what the alarm said
# ---------------------------------------------------------------------------
def step_week(key, delta, last):
    """Button callback: move the week slider by delta weeks, staying inside the year."""
    st.session_state[key] = max(0, min(last, st.session_state[key] + delta))


def tab_replay():
    transfer_note()
    hist = pred[pred["fips"] == fips]
    if hist.empty:
        st.info("No replay data for this county.")
        return

    # Pick a year. Default: the year with the most severe-drought weeks for this county.
    years = sorted(hist["date"].dt.year.unique())
    worst = hist.groupby(hist["date"].dt.year)["y"].sum().idxmax()
    year = st.selectbox("Year", years, index=years.index(worst), key=f"year_{fips}")
    wk = hist[hist["date"].dt.year == year].reset_index(drop=True)
    last = len(wk) - 1

    alarm_name = st.selectbox("Which alarm to show", list(ALARM_CHOICES))
    alarm_col = ALARM_CHOICES[alarm_name]

    # Week slider plus step buttons. The chosen week lives in session_state.
    key = f"week_{fips}_{year}"
    if key not in st.session_state:
        st.session_state[key] = 0
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
                             name="Drought class"))
    fig.add_trace(go.Scatter(x=alarms["date"], y=alarms["cls"], mode="markers", name="Alarm",
                             marker=dict(size=11, color="#d62728", symbol="triangle-up")))
    fig.add_hline(y=3, line_dash="dash", line_color="gray",
                  annotation_text="D2 severe", annotation_position="top left")
    fig.add_shape(type="line", x0=chosen_date, x1=chosen_date, y0=-0.2, y1=5.2,
                  line=dict(color="black", width=2))
    fig.update_xaxes(range=[wk["date"].min(), wk["date"].max()])
    fig.update_yaxes(range=[-0.2, 5.2], tickvals=list(CLASS_WORDS), ticktext=list(CLASS_WORDS.values()))
    fig.update_layout(height=400, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, width="stretch")

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
def kv_table(d):
    """Turn the single values of a dict into a two-column table."""
    rows = [(k.replace("_", " "), str(v)) for k, v in d.items() if not isinstance(v, (dict, list))]
    return pd.DataFrame(rows, columns=["Measure", "Value"])


def colored(df, good):
    """Green row when `good` is True, red when False. Used for the other-rivers tables."""
    def paint(row):
        color = "#d4edda" if good.loc[row.name] else "#f8d7da"
        return [f"background-color: {color}; color: #111"] * len(row)
    return df.style.apply(paint, axis=1)


def tab_how_good():
    transfer_note()
    m = metrics
    yes_no = lambda flag: "yes" if flag else "no"  # noqa: E731

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
    st.write(f"Our system cost **{h['system_cost']}** against **{h['persistence_cost']}** for "
             f"'the future equals today' ({h['pct_cheaper_than_persistence']}% cheaper). "
             f"The cheapest simple rule was **{h['cheapest_baseline_on_test']}** at "
             f"**{h['cheapest_baseline_cost']}**.")
    st.write(f"Honesty check (beats every simple rule on years it never saw): **{verdict}**")
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
    st.caption(m["season"]["target"])
    st.dataframe(kv_table(sf), hide_index=True)
    st.write(f"Beats every baseline: **{yes_no(sf['beats_every_baseline'])}**")

    # 3) The 12-month outlook.
    yf = m["year"]["focus"]
    st.header("12-month outlook")
    st.caption(m["year"]["target"] + ". Errors are in weeks; lower is better.")
    st.dataframe(kv_table(yf), hide_index=True)
    st.write(f"Beats every baseline: **{yes_no(yf['beats_every_baseline'])}**")
    bars = {"Our system": yf["mae_system"], "Same as now": yf["mae_same_as_now"],
            "Same as last year": yf["mae_last_year"], "Usual for the county": yf["mae_usual"]}
    st.plotly_chart(go.Figure(go.Bar(x=list(bars), y=list(bars.values()))).update_layout(
        height=300, yaxis_title="Average error (weeks)", margin=dict(l=10, r=10, t=10, b=10)),
        width="stretch")

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
    for f in m["failure_examples"]:
        st.write(f"- **{f['product']}**, {f['date']}, {f['county']}, {f['state']}: {f['what_happened']}")

    # 6) Extra checks and the plain list of limits.
    st.header("Extra checks and limits")
    st.dataframe(pd.DataFrame(m["ablations"]), hide_index=True, width="stretch")
    fi = pd.DataFrame(m["feature_importance"])
    st.plotly_chart(go.Figure(go.Bar(x=fi["importance"], y=fi["feature"], orientation="h")).update_layout(
        height=300, xaxis_title="Importance", margin=dict(l=10, r=10, t=10, b=10)),
        width="stretch")
    for sentence in m["limits"]:
        st.write(f"- {sentence}")


# ---------------------------------------------------------------------------
# Put the tabs on the page
# ---------------------------------------------------------------------------
tabs = st.tabs(["This week", "Replay", "How good is it"])
with tabs[0]:
    tab_this_week()
with tabs[1]:
    tab_replay()
with tabs[2]:
    tab_how_good()

st.divider()
st.caption("Drought data: U.S. Drought Monitor (NDMC, USDA, NOAA), county archive by the Montana "
           "Climate Office. ENSO index: NOAA Climate Prediction Center.")
