"""The demo page shares out the sealant budget itself. It must give the pipeline's own totals."""
import json

from farmdrought.config import METRICS, ROOT


def test_demo_page_rule_reproduces_the_pipeline_plan():
    text = (ROOT / "demo" / "data.js").read_text()
    demo = json.loads(text[len("window.DEMO = "):-2])
    with open(METRICS) as f:
        block = json.load(f)["districts"]
    plan = demo["sealant"]
    # the page's rule: canals in rank order, while the running total still fits inside the budget
    ranked = sorted((c for c in demo["canals"] if c[9]), key=lambda c: c[9])   # c[9] = sealant rank
    spent = km = 0
    for canal in ranked:
        if spent + canal[10] > plan["budget"]:                                  # c[10] = cost in dollars
            break
        spent, km = spent + canal[10], km + canal[4]                            # c[4] = length in km
    assert round(spent) == block["spent_usd"] and abs(km - block["sealed_km"]) < 0.5
    assert len(demo["districts"]) == block["n_districts"]
    assert demo["week"] == json.load(open(METRICS))["latest_week"]              # demo data is not stale
