"""Everrest RFM - v1 (first pass, pre expert review).

Objective: where should Everrest's CRM team spend its Q3 retention budget?

Run:  python rfm_everrest_v1.py  ->  writes ./output_v1/*.png
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

SEED = 42
DATA = Path(__file__).parent / "data"
OUT = Path(__file__).parent / "output_v1"
OUT.mkdir(exist_ok=True)
REF_DATE = pd.Timestamp("2026-07-01")

TEAL, SKY, INK, MUTED, HAIR = "#0D9488", "#38BDF8", "#0F172A", "#64748B", "#E2E8F0"
plt.rcParams.update(
    {
        "figure.dpi": 100,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "axes.titleweight": "bold",
    }
)

orders = pd.read_csv(DATA / "orders.csv", parse_dates=["order_ts"])
items = pd.read_csv(DATA / "order_items.csv")
items["net"] = items.qty * items.unit_price * (1 - items.discount)
ov = items.groupby("order_id").net.sum()
orders = orders.merge(ov.rename("order_value"), on="order_id", how="left")

# v1: naive RFM on ALL orders (bug: includes returned orders in monetary).
rfm = orders.groupby("customer_id").agg(
    recency=("order_ts", lambda s: (REF_DATE - s.max()).days),
    frequency=("order_id", "count"),
    monetary=("order_value", "sum"),
)

# scores 1-5
rfm["R"] = pd.qcut(rfm.recency, 5, labels=[5, 4, 3, 2, 1]).astype(int)
rfm["F"] = pd.qcut(
    rfm.frequency.rank(method="first"), 5, labels=[1, 2, 3, 4, 5]
).astype(int)
rfm["M"] = pd.qcut(rfm.monetary, 5, labels=[1, 2, 3, 4, 5]).astype(int)

# 1 - R/F/M distributions
fig, axes = plt.subplots(1, 3, figsize=(12, 3.5))
for ax, col, c in zip(axes, ["recency", "frequency", "monetary"], [TEAL, SKY, INK]):
    ax.hist(rfm[col], bins=40, color=c)
    ax.set_title(col.title())
fig.savefig(OUT / "rfm_distributions.png")
plt.close(fig)

# 2 - segment count (crude: RF combos)
rfm["seg"] = rfm.R.astype(str) + rfm.F.astype(str)
top = rfm.seg.value_counts().head(15)
fig, ax = plt.subplots(figsize=(9, 4))
ax.bar(top.index, top.values, color=TEAL)
ax.set_title("Customers by RF code")
fig.savefig(OUT / "segment_counts.png")
plt.close(fig)

# 3 - monetary pareto
m = rfm.monetary.sort_values(ascending=False).values
fig, ax = plt.subplots(figsize=(9, 4))
ax.plot(np.arange(len(m)) / len(m) * 100, np.cumsum(m) / m.sum() * 100, color=TEAL)
ax.set_title("Monetary pareto")
fig.savefig(OUT / "monetary_pareto.png")
plt.close(fig)

# 4 - R vs F scatter
fig, ax = plt.subplots(figsize=(7, 5))
ax.scatter(rfm.recency, rfm.frequency, s=6, alpha=0.2, color=TEAL)
ax.set_title("Recency vs Frequency")
fig.savefig(OUT / "recency_frequency.png")
plt.close(fig)

print(f"v1 charts -> {OUT}")
