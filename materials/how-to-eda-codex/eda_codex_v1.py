"""Everrest EDA - Codex edition, v1 (PRE expert review). Kept for the record.

This is the naive first pass, before the reviewer panel. It runs clean and
produces plausible-looking charts - which is exactly why it is dangerous. Every
flaw below was caught in Step 6 and fixed in eda_codex_v2.py:

  - No referential-integrity check: orphan product/customer keys silently
    dropped or turned to NaN, never surfaced.
  - Revenue grouped by the RAW merchant.category, so 'electronics' and
    'Electronics' land in different buckets (dirty labels split the rollup).
  - Payment latency plotted in aggregate, so the PH negative-latency tail is
    invisible (no per-region split).
  - No Benford / round-number check, no duplicate-identity check, no stale-price
    reconciliation - three planted defects missed entirely.
  - Cancelled and orphan orders included in revenue.
  - Charts titled by technique ('Revenue by category', 'Latency histogram').

Run:  python eda_codex_v1.py   ->  charts to ./output_v1/
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

HERE = Path(__file__).parent
DATA = HERE / "data"
OUT = HERE / "output_v1"
OUT.mkdir(exist_ok=True)
CYAN = "#0891B2"

orders = pd.read_csv(DATA / "orders.csv", parse_dates=["order_ts"])
items = pd.read_csv(DATA / "order_items.csv")
merchants = pd.read_csv(DATA / "merchants.csv")
payments = pd.read_csv(DATA / "payments.csv", parse_dates=["paid_ts"])

# Naive revenue: no dedup, no cancelled filter, no RI check.
items["net"] = items.qty * items.unit_price * (1 - items.discount)
order_value = items.groupby("order_id").net.sum()
orders = orders.merge(order_value.rename("order_value"), on="order_id", how="left")
orders = orders.merge(merchants[["merchant_id", "category"]], on="merchant_id")

# FLAW: group by the RAW (dirty) category - splits Electronics/electronics etc.
rev_by_cat = orders.groupby("category").order_value.sum().sort_values()
fig, ax = plt.subplots(figsize=(8, 5))
ax.barh(rev_by_cat.index, rev_by_cat.values / 1e3, color=CYAN)
ax.set_title("Revenue by category")  # technique title, and the buckets are wrong
ax.set_xlabel("revenue ($k)")
fig.savefig(OUT / "v1_revenue_by_category.png", dpi=120, bbox_inches="tight")
plt.close(fig)

# FLAW: payment latency in aggregate - the PH negative tail averages out.
lat = (
    payments.paid_ts
    - orders.set_index("order_id").order_ts.reindex(payments.order_id).values
)
lat_h = lat.dt.total_seconds() / 3600
fig, ax = plt.subplots(figsize=(8, 4))
ax.hist(lat_h.dropna().clip(0, 5), bins=40, color=CYAN)  # clip(0,..) HIDES negatives
ax.set_title("Latency histogram")
ax.set_xlabel("hours")
fig.savefig(OUT / "v1_latency.png", dpi=120, bbox_inches="tight")
plt.close(fig)

print("v1 revenue buckets (note the split labels):")
print(rev_by_cat.round(0).to_string())
print(f"\nv1 mean 'latency' (hides negatives via clip): {lat_h.clip(0,5).mean():.2f}h")
print(f"v1 total revenue (incl cancelled + orphans): ${orders.order_value.sum():,.0f}")
