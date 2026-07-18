"""Step 4 head start: one-shot profiling report.

Codex's find-skills step pulls a profiling library so the analyst does not
hand-write describe() on eight tables. This uses sweetviz (works on Python
3.13); ydata-profiling is the equivalent card in the toolbox and drops in with
`ProfileReport(df).to_file(...)` if your env supports it.

Run:  python profile_report.py  ->  writes report.html (screenshot -> page)
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import sweetviz as sv

HERE = Path(__file__).parent
DATA = HERE / "data"

# The order_items x products join is where the price-drift and orphan quirks
# hide, so profile the enriched line-item table - the busiest table on Everrest.
items = pd.read_csv(DATA / "order_items.csv")
products = pd.read_csv(DATA / "products.csv")
enriched = items.merge(
    products[["product_id", "price", "category"]], on="product_id", how="left"
)
enriched["price_gap"] = (enriched.unit_price - enriched.price).round(2)

report = sv.analyze(enriched, pairwise_analysis="off")
report.show_html(str(HERE / "report.html"), open_browser=False, layout="vertical")
print("wrote", HERE / "report.html", "rows:", len(enriched))
