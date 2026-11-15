"""
brief.py - writes the plain-English "Farm brief" for one county.

It is plain template text: no internet, no AI model. Same inputs always give the same brief.
It only reads today's forecast row plus the county's PAST drought class - never the truth
columns and never any row after the chosen week.
"""
import re

import pandas as pd

# Characters that could turn plain text from a data file into a link, an image, HTML, a
# color tag (:red[...]) or math. We put a backslash in front so they show as plain characters.
_MARKDOWN_SPECIAL = re.compile(r"([\\\[\]<>$`])")


def md_escape(text):
    """Make text from a data file safe to show as Markdown (it can't become a link, tag or HTML)."""
    return _MARKDOWN_SPECIAL.sub(r"\\\1", str(text))


# Drought Monitor classes in words (0..5).
CLASS_WORDS = {0: "None", 1: "D0 Abnormally dry", 2: "D1 Moderate", 3: "D2 Severe",
               4: "D3 Extreme", 5: "D4 Exceptional"}

# Three plain "things to think about" lines for each tier of the 4-week alert.
THINGS_TO_THINK_ABOUT = {
    "Low": ["No action is suggested by this forecast.",
            "Keep watching the weekly Drought Monitor map.",
            "Check back next week."],
    "Watch": ["Check your hay and water plans.",
              "Talk with neighbors or your irrigation district about conditions.",
              "Keep watching: this can change within weeks."],
    "Warning": ["Review stocking and feed plans.",
                "Gather records your county FSA office may ask for.",
                "Talk with your county FSA office early."],
}


def streak_sentence(streak):
    """The sentence about USDA's Livestock Forage Disaster Program. '' if not in severe drought."""
    if 1 <= streak <= 7:
        return (f"In severe drought for {streak} weeks in a row. USDA's Livestock Forage Disaster "
                "Program can open at 8 consecutive weeks during the grazing period. "
                "Check with your county FSA office.")
    if streak >= 8:
        return ("8 or more weeks in a row. Ask your county FSA office about the "
                "Livestock Forage Disaster Program.")
    return ""


def build_brief(latest_row, history, metrics, status):
    """
    latest_row : one row of latest.parquet (a pandas Series) for the county
    history    : that county's past rows (needs only 'date' and 'cls'); rows after the
                 chosen week are ignored
    metrics    : the metrics.json dictionary
    status     : "DEMO", "PROVISIONAL" or "FINAL"
    Returns the brief as Markdown text.
    """
    r = latest_row
    week = pd.Timestamp(r["date"])
    mae = metrics["year"]["focus"]["mae_system"]
    county, state, river = md_escape(r["county"]), md_escape(r["state"]), md_escape(r["river"])
    lines = [f"# Farm brief: {county}, {state}",
             f"**Status: {status}**  |  River: {river}  |  Week of {week:%B %d, %Y}", ""]

    # The three products, in plain sentences.
    lines += ["## What the forecast says",
              f"- **Next 4 weeks:** {r['tier']} (risk score {round(r['p_model'] * 100)}%). "
              "This is a risk score, not a calibrated probability.",
              f"- **Next 6 months:** about a {round(r['p_season'] * 100)}% chance of 8 straight weeks "
              "of severe drought.",
              f"- **Next 12 months:** about {round(r['weeks_model'])} weeks of severe drought, "
              f"where this county usually sees {round(r['weeks_usual'])}. "
              f"This is a planning range: the typical error is about {mae} weeks.", ""]

    # Drought class now, and how it changed. Only rows ON OR BEFORE 4 weeks earlier are used.
    now = int(r["cls"])
    lines += ["## Where things stand", f"- Drought class now: {CLASS_WORDS[now]}."]
    past = history[history["date"] <= week - pd.Timedelta(weeks=4)]
    if not past.empty:
        before = past.sort_values("date").iloc[-1]
        change = now - int(before["cls"])
        word = "worse" if change > 0 else "better" if change < 0 else "unchanged"
        lines.append(f"- Compared with the week of {before['date']:%b %d} "
                     f"({CLASS_WORDS[int(before['cls'])]}): {word}.")
    note = streak_sentence(int(r["d2_streak"]))
    if note:
        lines.append(f"- {note}")
    lines.append("")

    # Things to think about depend on the tier.
    lines.append("## Things to think about")
    lines += [f"- {t}" for t in THINGS_TO_THINK_ABOUT[r["tier"]]]
    lines.append("")

    # Honest limits.
    lines.append("## Limits")
    first_limit = metrics["limits"][0] if metrics["limits"] else ""
    if first_limit:
        lines.append(f"- {md_escape(first_limit)}")
    if r["river"] != metrics["focus_river"]:
        lines.append(f"- The model was trained on the {md_escape(metrics['focus_river'])}, not on this river. "
                     "Treat this as a test, not a product.")
    lines += ["- This is a forecast tool, not a payment decision. Not financial or legal advice."]
    return "\n".join(lines) + "\n"
