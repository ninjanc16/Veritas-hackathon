"""
theme.py - how the app LOOKS. No data logic lives here.

Design idea (for the judges): the app should feel like a field journal for people who work
the land - warm paper, forest green, river blue, and earth tones that run from sage (fine)
to ochre (watch out) to clay red (drought). Headings use a classic serif; everything else is
plain and quiet so the numbers stand out.

Three things live here:
  1. the color palettes (light and dark) and the earth-tone colors used in charts,
  2. apply_theme(): one block of CSS that restyles the whole page,
  3. small helpers that draw the hero banner, the forecast cards and the charts' look.

Safety note: the only HTML we write is built here, and every piece of text that came from
data goes through html.escape() first. The CSS itself is fixed text.
"""
import html
import math
from string import Template

import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
LIGHT = dict(
    bg="#f4f1e8", surface="#fbf9f3", ink="#1d2b24", muted="#5b6a60", line="#d8d2c2",
    forest="#2f5d46", forest_deep="#1d3a2c", river="#2c6e7f", sidebar="#1f3d30",
    sidebar_ink="#eef0e4", tint="#e6eadb", paper_plot="rgba(0,0,0,0)",
    heading="#1d3a2c", field_ink="#1d2b24", map_style="carto-positron")      # heading = titles and big numbers; field_ink = text inside inputs
DARK = dict(
    bg="#121a16", surface="#1a2520", ink="#e8e4d6", muted="#9fada4", line="#2c3a32",
    forest="#86bb97", forest_deep="#0f1914", river="#6fb3c4", sidebar="#0d1511",
    sidebar_ink="#e8e4d6", tint="#22302a", paper_plot="rgba(0,0,0,0)",
    heading="#eae6d6", field_ink="#e8e4d6", map_style="carto-darkmatter")

# Warning tiers, as earth tones: sage -> ochre -> clay.
TIER_COLOR = {"Low": "#7a9e7e", "Watch": "#d4a031", "Warning": "#b5472f"}

# Drought class 0..5 (none ... exceptional): pale sand darkening to deep soil brown.
DROUGHT_SCALE = [[0.0, "#f3ecd8"], [0.2, "#e8d9a8"], [0.4, "#d9b45f"],
                 [0.6, "#c47f3a"], [0.8, "#a8482f"], [1.0, "#6e2a1f"]]

# Line colors for charts, in the order plotly picks them.
CHART_COLORS = ["#2c6e7f", "#2f5d46", "#d4a031", "#b5472f", "#7a9e7e"]


def palette():
    """Light or dark colors, to match how the viewer has Streamlit set up."""
    try:
        return DARK if st.context.theme.get("type") == "dark" else LIGHT
    except Exception:          # older Streamlit or no theme info: use light
        return LIGHT


# ---------------------------------------------------------------------------
# The page CSS. $name placeholders are filled from the palette above.
# ---------------------------------------------------------------------------
CSS = Template("""
<style>
:root { --serif: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif; }

/* page and text */
.stApp { background: $bg; }
.stApp p, .stApp li, .stApp label, .stApp span, .stApp div { color: $ink; }
.stMarkdown p, .stMarkdown li { line-height: 1.6; }
.block-container { padding-top: 2.2rem; max-width: 1180px; }
[data-testid="stHeader"] { background: transparent; }
.stAppDeployButton { display: none; }

/* headings in a serif, with a thin rule under the big ones */
h1, h2, h3, h4 { font-family: var(--serif) !important; color: $heading !important;
                 letter-spacing: -0.01em; font-weight: 600 !important; }
h2 { border-bottom: 1px solid $line; padding-bottom: .35rem; margin-top: 2rem !important; }
.stCaption, [data-testid="stCaptionContainer"] { color: $muted !important; }

/* tabs: quiet text, forest-green underline under the chosen one */
[role="tablist"] { gap: .4rem; border-bottom: 1px solid $line; }
[data-testid="stTab"] { padding: .7rem .9rem; }
[data-testid="stTab"] p { font-size: 1rem; font-weight: 600; color: $muted; }
[data-testid="stTab"][aria-selected="true"] p { color: $heading; }
.react-aria-SelectionIndicator { background-color: $forest !important; height: 3px !important; }

/* slider and toggle: Streamlit draws them in its default red, so we rotate that red to green */
[data-testid="stSlider"] [style*="position: relative"][style*="touch-action: none"],
label:has(input[role="switch"]) > div { filter: hue-rotate(150deg) saturate(.75) brightness(.85); }

/* sidebar: deep forest green. (".stApp" in front makes these win over the general text color) */
.stApp [data-testid="stSidebar"] { background: $sidebar; }
.stApp [data-testid="stSidebar"] * { color: $sidebar_ink; }
.stApp [data-testid="stSidebar"] [data-testid="stSelectbox"] input { color: $field_ink; -webkit-text-fill-color: $field_ink; }
.stApp [data-testid="stSidebar"] [data-testid="stSelectbox"] svg { color: $field_ink; fill: $field_ink; }
.stApp [data-testid="stSidebar"] [data-testid="stAlert"] * { color: $field_ink; }
.stApp [data-testid="stSidebar"] h4 { font-family: var(--serif) !important; color: $sidebar_ink !important; }
.brand { font-family: var(--serif); font-size: 1.25rem; line-height: 1.2; margin: .2rem 0 .3rem; }
.brand-sub { font-size: .8rem; opacity: .75; margin-bottom: 1.2rem; }

/* hero banner at the top of the page */
.hero { position: relative; overflow: hidden; border-radius: 10px; padding: 2.2rem 2.4rem 1.8rem;
  margin-bottom: 1.4rem; color: #f3f1e6;
  background-color: #1f3d30;
  background-image:
    url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 900 260' preserveAspectRatio='none'><g fill='none' stroke='rgba(255,255,255,0.13)' stroke-width='1.4'><path d='M0 190 C150 120 250 250 420 180 S700 90 900 150'/><path d='M0 215 C160 150 270 275 440 205 S710 118 900 176'/><path d='M0 240 C170 180 290 300 460 230 S720 146 900 202'/><path d='M0 165 C140 95 240 225 400 155 S690 62 900 124'/></g></svg>"),
    linear-gradient(115deg, #1d3a2c 0%, #2f5d46 55%, #2c6e7f 120%);
  background-size: cover; background-position: center; }
.hero * { color: #f3f1e6 !important; }
.hero-kicker { font-size: .74rem; letter-spacing: .16em; text-transform: uppercase; opacity: .8; }
.hero-title { font-family: var(--serif); font-size: 2.5rem; line-height: 1.1; margin: .5rem 0 .6rem;
  font-weight: 600; border: none; padding: 0; }
.hero-sub { max-width: 46rem; font-size: 1.02rem; opacity: .92; margin: 0 0 1rem; }
.chip { display: inline-block; font-size: .78rem; padding: .2rem .7rem; margin-right: .5rem;
  border: 1px solid rgba(243,241,230,.55); border-radius: 999px; }

/* forecast cards: a grid, so all cards are the same height */
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1rem;
  margin: .4rem 0 1.2rem; }
.card { background: $surface; border: 1px solid $line; border-top: 4px solid var(--accent);
  border-radius: 8px; padding: 1.1rem 1.2rem 1rem; }
.card-label { font-size: .72rem; letter-spacing: .14em; text-transform: uppercase; color: $muted !important; }
.card-value { font-family: var(--serif); font-size: 2.2rem; line-height: 1.15; margin: .35rem 0 .1rem;
  color: $heading !important; }
.card-caption { font-size: .88rem; color: $muted !important; margin-bottom: .6rem; }
.card-row { font-size: .9rem; padding-top: .4rem; margin-top: .4rem; border-top: 1px solid $line; }
.dot { display: inline-block; width: .7rem; height: .7rem; border-radius: 50%; margin-right: .45rem;
  background: var(--accent); }

/* a gentle note box, used for the USDA program sentence */
.callout { border-left: 4px solid #d4a031; background: $tint; padding: .8rem 1rem; border-radius: 4px;
  margin: .2rem 0 .6rem; font-size: .95rem; }

/* buttons */
.stButton button, .stDownloadButton button { border: 1px solid $forest; color: $heading;
  background: transparent; border-radius: 6px; }
.stButton button:hover, .stDownloadButton button:hover { background: $forest; color: #f3f1e6; border-color: $forest; }
.stButton button:hover p, .stDownloadButton button:hover p { color: #f3f1e6; }

/* boxes Streamlit draws for success/warning/info */
[data-testid="stAlert"] { border-radius: 6px; }

.footer { margin-top: 2.5rem; padding-top: 1rem; border-top: 1px solid $line; font-size: .82rem; color: $muted; }
</style>
""")


def apply_theme():
    """Paint the whole page. Call once, right after st.set_page_config."""
    st.markdown(CSS.substitute(palette()), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Small building blocks. Every piece of text is escaped before it goes into HTML.
# ---------------------------------------------------------------------------
def hero(title, kicker, subtitle, chips):
    """The banner at the top: small label, big title, one sentence, and little status chips."""
    chip_html = "".join(f'<span class="chip">{html.escape(c)}</span>' for c in chips)
    st.markdown(
        f'<div class="hero"><div class="hero-kicker">{html.escape(kicker)}</div>'
        f'<h1 class="hero-title">{html.escape(title)}</h1>'
        f'<p class="hero-sub">{html.escape(subtitle)}</p>{chip_html}</div>',
        unsafe_allow_html=True)


def sidebar_brand(name, sub):
    """Small name plate at the top of the sidebar."""
    st.sidebar.markdown(f'<div class="brand">{html.escape(name)}</div>'
                        f'<div class="brand-sub">{html.escape(sub)}</div>', unsafe_allow_html=True)


def card_grid(cards):
    """
    Draw a row of cards. Each card is a dict:
      label   small heading, e.g. "Next 4 weeks"
      value   the big text, e.g. "Low" or "23%"
      caption one line under the value
      rows    list of extra lines at the bottom
      accent  color of the card's top edge (and of the dot, if dot=True)
      dot     True to put a colored dot before the value
    """
    out = []
    for c in cards:
        accent = c.get("accent", "#2f5d46")
        dot = '<span class="dot"></span>' if c.get("dot") else ""
        rows = "".join(f'<div class="card-row">{html.escape(r)}</div>' for r in c.get("rows", []))
        out.append(
            f'<div class="card" style="--accent:{html.escape(accent)}">'
            f'<div class="card-label">{html.escape(c["label"])}</div>'
            f'<div class="card-value">{dot}{html.escape(c["value"])}</div>'
            f'<div class="card-caption">{html.escape(c.get("caption", ""))}</div>{rows}</div>')
    st.markdown(f'<div class="cards">{"".join(out)}</div>', unsafe_allow_html=True)


def callout(text):
    """A soft note box (the text is escaped)."""
    st.markdown(f'<div class="callout">{html.escape(text)}</div>', unsafe_allow_html=True)


def footer(text):
    st.markdown(f'<div class="footer">{html.escape(text)}</div>', unsafe_allow_html=True)


def style_fig(fig, height=None):
    """Give a plotly chart the same look as the page: transparent background, soft grid, our colors."""
    p = palette()
    fig.update_layout(
        paper_bgcolor=p["paper_plot"], plot_bgcolor=p["paper_plot"], colorway=CHART_COLORS,
        font=dict(family='"Iowan Old Style","Palatino Linotype",Georgia,serif', color=p["ink"], size=13),
        hoverlabel=dict(bgcolor=p["surface"], font=dict(color=p["ink"])),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, bgcolor="rgba(0,0,0,0)"))
    fig.update_xaxes(gridcolor=p["line"], zerolinecolor=p["line"], linecolor=p["line"])
    fig.update_yaxes(gridcolor=p["line"], zerolinecolor=p["line"], linecolor=p["line"])
    if height:
        fig.update_layout(height=height)
    return fig


def risk_map(df, selected_fips, river_lines=None, river_name="River", level_col="tier",
             height=520, width_px=980):
    """
    A real, zoomable map of the counties in `df` (one river).
      - the river itself is drawn as a blue line (river_lines = list of [(lat, lon), ...] pieces)
      - each county is a dot, colored by `level_col` ("risk_level" = the worse of the 4-week and
        6-month levels, or "tier" = the 4-week level if the pipeline's map columns are missing)
      - hovering shows the county's forecasts; clicking selects it (customdata = its county code)
    The map tiles (streets, terrain) come from a free public tile server, fetched by the viewer's
    browser (no account or key). If the tiles can't load, the river and dots still show.
    """
    p = palette()
    fig = go.Figure()

    # The river: one blue line. None between the pieces lifts the pen so they are not joined.
    if river_lines:
        lats, lons = [], []
        for piece in river_lines:
            lats += [pt[0] for pt in piece] + [None]
            lons += [pt[1] for pt in piece] + [None]
        fig.add_trace(go.Scattermap(lat=lats, lon=lons, mode="lines", name=river_name, hoverinfo="skip",
                                    line=dict(width=3, color=p["river"])))

    # A soft halo behind the selected county, drawn before the dots so it sits under them.
    sel = df[df["fips"] == selected_fips]
    fig.add_trace(go.Scattermap(lat=sel["lat"], lon=sel["lon"], mode="markers", hoverinfo="skip",
                                name="Selected county", marker=dict(size=34, color=p["forest"], opacity=0.35)))

    has_range = "weeks_low" in df.columns and "weeks_high" in df.columns
    has_spells = "typical_drought_weeks" in df.columns and "longest_drought_weeks" in df.columns
    for level, color in TIER_COLOR.items():
        sub = df[df[level_col] == level]
        hover = []
        for r in sub.itertuples():
            lines = [f"<b>{html.escape(r.county)}, {html.escape(r.state)}</b>"]
            if level_col != "tier":
                lines.append(f"Overall level: {html.escape(str(getattr(r, level_col)))}")
            lines.append(f"4-week: {html.escape(r.tier)}")
            lines.append(f"6-month: {round(r.p_season * 100)}% chance")
            weeks = f"12-month: about {round(r.weeks_model)} weeks"
            if has_range:
                weeks += f" (range {round(r.weeks_low)} to {round(r.weeks_high)})"
            lines.append(weeks)
            if has_spells:
                lines.append(f"Past spells: typical {round(r.typical_drought_weeks)}, "
                             f"longest {round(r.longest_drought_weeks)} weeks")
            hover.append("<br>".join(lines))
        fig.add_trace(go.Scattermap(lat=sub["lat"], lon=sub["lon"], mode="markers", name=level,
                                    text=hover, hoverinfo="text", customdata=sub[["fips"]],
                                    marker=dict(size=15, color=color)))

    # Zoom so every county fits: work out how many degrees we must show, then the zoom level
    # (a world map tile is 512 px wide at zoom 0 and the width halves with every zoom step).
    lat_span = max(df["lat"].max() - df["lat"].min(), 0.5)
    lon_span = max((df["lon"].max() - df["lon"].min()) * math.cos(math.radians(df["lat"].mean())), 0.5)
    zoom = min(math.log2(height * 360 / (512 * lat_span * 1.5)),
               math.log2(width_px * 360 / (512 * lon_span * 1.5)), 9)
    fig.update_layout(map=dict(style=p["map_style"], zoom=zoom,
                               center=dict(lat=float(df["lat"].mean()), lon=float(df["lon"].mean()))),
                      margin=dict(l=0, r=0, t=0, b=0),
                      legend_title_text="Overall level" if level_col != "tier" else "4-week level")
    return style_fig(fig, height)


# Canal levels (from the pipeline) -> line colors. Same sage / ochre / clay as the tiers,
# plus grey for "no published seepage rate" and slate blue for drains.
CANAL_COLOR = {"Inspect first": "#b5472f", "Watch": "#d4a031", "Low": "#7a9e7e",
               "Unknown soil": "#9a9a92", "Drain": "#5b7f95"}


def canal_map(segments, height=560, width_px=980):
    """
    Zoomable map of one county's canals. `segments` = the list from mapdata.load_canals()[fips].
    One line trace per level (so the legend can switch levels on and off). Named canals show their
    name, soil and seepage rate on hover; unnamed ones are plain lines.
    """
    p = palette()
    fig = go.Figure()
    # Draw in reverse so the important level ("Inspect first") is painted last, on top of the rest.
    for level, color in reversed(list(CANAL_COLOR.items())):
        lats, lons, hover = [], [], []
        for seg in (s for s in segments if s["level"] == level):
            tip = (f"<b>{html.escape(seg['name'])}</b><br>{html.escape(seg['soil'] or 'soil unknown')}"
                   f"<br>{html.escape(level)}" if seg["name"] else "")
            for lat, lon in seg["line"]:
                lats.append(lat); lons.append(lon); hover.append(tip)
            lats.append(None); lons.append(None); hover.append("")      # lift the pen between segments
        if lats:
            fig.add_trace(go.Scattermap(lat=lats, lon=lons, mode="lines", name=level, text=hover,
                                        hoverinfo="text", line=dict(width=5 if level == "Inspect first" else 2,
                                                                    color=color)))
    pts = [pt for seg in segments for pt in seg["line"]]
    lat_min, lat_max = min(a for a, _ in pts), max(a for a, _ in pts)
    lon_min, lon_max = min(b for _, b in pts), max(b for _, b in pts)
    lat_c, lon_c = (lat_min + lat_max) / 2, (lon_min + lon_max) / 2
    lat_span = max(lat_max - lat_min, 0.05)
    lon_span = max((lon_max - lon_min) * math.cos(math.radians(lat_c)), 0.05)
    zoom = min(math.log2(height * 360 / (512 * lat_span * 1.2)),
               math.log2(width_px * 360 / (512 * lon_span * 1.2)), 12)
    fig.update_layout(map=dict(style=p["map_style"], zoom=zoom, center=dict(lat=lat_c, lon=lon_c)),
                      margin=dict(l=0, r=0, t=0, b=0), legend_title_text="Canal level", legend_traceorder="reversed")
    return style_fig(fig, height)
