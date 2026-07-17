"""Everrest EDA - v1 (first pass, pre mentor review).

Objective: what should Everrest's category team act on this quarter,
and what in this data can't be trusted yet?

Run:  python eda_everrest_v1.py  ->  writes ./output_v1/*.png
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from statsmodels.tsa.seasonal import seasonal_decompose

SEED = 42
DATA = Path(__file__).parent / "data"
OUT = Path(__file__).parent / "output_v1"
OUT.mkdir(exist_ok=True)

# Steel teal chart discipline
TEAL, SKY, INK, MUTED, HAIR = "#0D9488", "#38BDF8", "#0F172A", "#64748B", "#E2E8F0"
plt.rcParams.update(
    {
        "figure.dpi": 100,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "font.family": "sans-serif",
        "axes.edgecolor": HAIR,
        "axes.labelcolor": INK,
        "axes.grid": True,
        "grid.color": HAIR,
        "grid.linewidth": 0.6,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
    }
)

orders = pd.read_csv(DATA / "orders.csv", parse_dates=["order_ts"])
order_items = pd.read_csv(DATA / "order_items.csv")
merchants = pd.read_csv(DATA / "merchants.csv", parse_dates=["joined_at"])
products = pd.read_csv(DATA / "products.csv")
customers = pd.read_csv(DATA / "customers.csv", parse_dates=["signup_date"])
payments = pd.read_csv(DATA / "payments.csv", parse_dates=["paid_ts"])
returns = pd.read_csv(DATA / "returns.csv", parse_dates=["return_ts"])

order_items["net"] = (
    order_items.qty * order_items.unit_price * (1 - order_items.discount)
)
order_value = order_items.groupby("order_id").net.sum().rename("order_value")
orders = orders.merge(order_value, on="order_id", how="left")
orders = orders.merge(merchants[["merchant_id", "tier", "category"]], on="merchant_id")

# 1 - revenue pareto by merchant
rev = orders.groupby("merchant_id").order_value.sum().sort_values(ascending=False)
cum = rev.cumsum() / rev.sum() * 100
fig, ax = plt.subplots(figsize=(9, 4.5))
ax.bar(range(60), rev.head(60) / 1e3, color=TEAL)
ax2 = ax.twinx()
ax2.plot(range(60), cum.head(60), color=SKY, lw=2)
ax2.set_ylim(0, 100)
ax2.set_ylabel("cumulative %", color=MUTED)
ax2.grid(False)
ax.set_title("Revenue concentration - top 60 merchants")
ax.set_ylabel("revenue ($k)")
fig.savefig(OUT / "revenue_pareto.png")
plt.close(fig)

# 2 - missingness matrix
tables = {
    "orders": orders,
    "order_items": order_items,
    "payments": payments,
    "customers": customers,
    "products": products,
    "returns": returns,
}
miss = pd.DataFrame({t: df.isna().mean() * 100 for t, df in tables.items()}).T
miss = miss.dropna(axis=1, how="all").fillna(0)
fig, ax = plt.subplots(figsize=(9, 3.6))
sns.heatmap(
    miss,
    annot=True,
    fmt=".1f",
    cmap=sns.light_palette(TEAL, as_cmap=True),
    cbar_kws={"label": "% missing"},
    linewidths=0.5,
    linecolor="white",
    ax=ax,
)
ax.set_title("Missing values by table and column (%)")
fig.savefig(OUT / "missingness_matrix.png")
plt.close(fig)

# 3 - order value distribution
fig, ax = plt.subplots(figsize=(9, 4))
ax.hist(orders.order_value.dropna(), bins=120, color=TEAL)
ax.set_title("Order value distribution")
ax.set_xlabel("order value ($)")
fig.savefig(OUT / "order_value_dist.png")
plt.close(fig)

# 4 - order value by merchant tier
fig, ax = plt.subplots(figsize=(9, 4))
sns.boxplot(
    data=orders,
    x="tier",
    y="order_value",
    color=TEAL,
    ax=ax,
    flierprops={"marker": ".", "markersize": 3, "color": MUTED},
)
ax.set_title("Order value by merchant tier")
fig.savefig(OUT / "order_value_by_tier.png")
plt.close(fig)

# 5 - daily demand + weekly decomposition
daily = orders.set_index("order_ts").resample("D").size()
dec = seasonal_decompose(daily, period=7)
fig, axes = plt.subplots(3, 1, figsize=(9, 6), sharex=True)
axes[0].plot(daily.index, daily.values, color=TEAL, lw=1)
axes[0].set_title("Daily orders")
axes[1].plot(dec.trend.index, dec.trend.values, color=SKY, lw=1.5)
axes[1].set_title("Trend")
axes[2].plot(dec.seasonal.index[:60], dec.seasonal.values[:60], color=INK, lw=1)
axes[2].set_title("Weekly seasonal (first 60 days)")
fig.savefig(OUT / "demand_decomposition.png")
plt.close(fig)

# 6 - orders by day of week x hour
pivot = (
    orders.assign(dow=orders.order_ts.dt.day_name().str[:3], hr=orders.order_ts.dt.hour)
    .pivot_table(index="dow", columns="hr", values="order_id", aggfunc="count")
    .reindex(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
)
fig, ax = plt.subplots(figsize=(9, 3.4))
sns.heatmap(
    pivot,
    cmap=sns.light_palette(TEAL, as_cmap=True),
    ax=ax,
    cbar_kws={"label": "orders"},
)
ax.set_title("Orders by day of week and hour")
fig.savefig(OUT / "dow_hour_heatmap.png")
plt.close(fig)

# 7 - correlation heatmap
num = orders.assign(
    items=orders.order_id.map(order_items.groupby("order_id").qty.sum()),
    discount=orders.order_id.map(order_items.groupby("order_id").discount.mean()),
)
corr = num[["order_value", "items", "discount"]].corr()
fig, ax = plt.subplots(figsize=(5, 4))
sns.heatmap(
    corr,
    annot=True,
    fmt=".2f",
    cmap=sns.diverging_palette(200, 170, as_cmap=True),
    vmin=-1,
    vmax=1,
    ax=ax,
)
ax.set_title("Correlations")
fig.savefig(OUT / "corr_heatmap.png")
plt.close(fig)

# 8 - monthly revenue by category (small multiples)
cat_month = (
    orders.assign(month=orders.order_ts.dt.to_period("M").dt.to_timestamp())
    .groupby(["month", "category"])
    .order_value.sum()
    .unstack()
)
fig, axes = plt.subplots(2, 4, figsize=(12, 5), sharex=True)
for ax, cat in zip(axes.flat, cat_month.columns):
    ax.plot(cat_month.index, cat_month[cat] / 1e3, color=TEAL, lw=1.5)
    ax.set_title(cat, fontsize=9)
    ax.tick_params(labelsize=7)
fig.suptitle("Monthly revenue by category ($k)", fontweight="bold")
fig.savefig(OUT / "category_small_multiples.png")
plt.close(fig)

# 9 - cohort retention
first = orders.groupby("customer_id").order_ts.min().dt.to_period("M").rename("cohort")
o = orders.join(first, on="customer_id")
o["age"] = (o.order_ts.dt.to_period("M") - o.cohort).apply(lambda p: p.n)
cohort = o.pivot_table(
    index="cohort", columns="age", values="customer_id", aggfunc="nunique"
)
ret = cohort.div(cohort[0], axis=0) * 100
fig, ax = plt.subplots(figsize=(9, 4.5))
sns.heatmap(
    ret.iloc[:, :10],
    annot=True,
    fmt=".0f",
    cmap=sns.light_palette(TEAL, as_cmap=True),
    cbar_kws={"label": "% active"},
    ax=ax,
)
ax.set_title("Monthly cohort retention (%)")
fig.savefig(OUT / "cohort_retention.png")
plt.close(fig)

# 10 - return rate by tier
delivered = orders[orders.status == "delivered"]
ret_rate = (
    delivered.order_id.isin(returns.order_id).groupby(delivered.tier).mean() * 100
)
fig, ax = plt.subplots(figsize=(7, 4))
ax.bar(ret_rate.index, ret_rate.values, color=TEAL)
ax.set_title("Return rate by merchant tier (%)")
ax.set_ylabel("% of delivered orders returned")
fig.savefig(OUT / "returns_by_tier.png")
plt.close(fig)

print(f"charts written to {OUT}")
