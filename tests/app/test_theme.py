"""Tests for theme.py: the HTML we build must never let data text turn into live HTML."""
from app import theme


def _capture(monkeypatch):
    """Replace st.markdown so we can look at the HTML the helpers would draw."""
    drawn = []
    monkeypatch.setattr(theme.st, "markdown", lambda body, **kwargs: drawn.append(body))
    return drawn


def test_card_grid_escapes_everything(monkeypatch):
    drawn = _capture(monkeypatch)
    theme.card_grid([dict(label="<script>alert(1)</script>", value="<img src=x onerror=1>",
                          caption="a & b", rows=["<b>bold</b>"], accent='red" onload="x', dot=True)])
    page = drawn[0]
    assert "<script" not in page and "<img" not in page and "<b>" not in page
    assert "&lt;script&gt;" in page and "a &amp; b" in page
    assert 'onload="x' not in page                       # the quote in the accent color was escaped


def test_hero_callout_and_footer_escape_text(monkeypatch):
    drawn = _capture(monkeypatch)
    theme.hero("<i>T</i>", "<k>", "<s>", ["<c>"])
    theme.callout("<u>note</u>")
    theme.footer("<em>f</em>")
    page = "".join(drawn)
    for tag in ("<i>", "<k>", "<s>", "<c>", "<u>", "<em>"):
        assert tag not in page


def test_palette_falls_back_to_light_when_theme_is_unknown(monkeypatch):
    class Broken:
        @property
        def theme(self):
            raise RuntimeError("no theme info")
    monkeypatch.setattr(theme.st, "context", Broken())
    assert theme.palette() is theme.LIGHT


def test_both_palettes_define_the_same_colors():
    assert set(theme.LIGHT) == set(theme.DARK)           # CSS asks for each name in both modes


def test_style_fig_makes_the_background_transparent():
    import plotly.graph_objects as go
    fig = theme.style_fig(go.Figure(), 300)
    assert fig.layout.paper_bgcolor == "rgba(0,0,0,0)" and fig.layout.height == 300


def _two_counties():
    import pandas as pd
    return pd.DataFrame({
        "fips": ["08003", "35001"], "county": ["Alamosa", "<b>Bad</b>"], "state": ["Colorado", "New Mexico"],
        "lat": [37.5, 35.0], "lon": [-105.8, -106.6], "tier": ["Low", "Warning"],
        "p_season": [0.2, 0.6], "weeks_model": [14.0, 30.0]})


def test_risk_map_has_a_dot_layer_per_tier_and_keeps_the_county_codes():
    fig = theme.risk_map(_two_counties(), "08003")
    names = [t.name for t in fig.data]
    assert names == ["Selected county", "Low", "Watch", "Warning"]
    assert list(fig.data[3].customdata[:, 0]) == ["35001"]       # a click can tell which county it was


def test_risk_map_is_centered_on_the_data_and_escapes_names():
    df = _two_counties()
    fig = theme.risk_map(df, "08003")
    assert min(df["lat"]) <= fig.layout.map.center.lat <= max(df["lat"])
    assert 3 < fig.layout.map.zoom < 9                              # sensible zoom for two nearby counties
    hover = "".join(fig.data[3].text)
    assert "<b>Bad" not in hover and "&lt;b&gt;Bad" in hover
