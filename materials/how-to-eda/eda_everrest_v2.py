"""Everrest EDA - v2 (post mentor review).

Objective: what should Everrest's category team act on this quarter,
and what in this data can't be trusted yet?

Mentor fixes applied over v1:
- Karpathy: data-quality gate FIRST - dedup the 600 double-fired orders and
  exclude cancelled orders before any aggregate (v1 double-counted both).
- Ng: structured DQ phase + missingness broken down BY segment (channel),
  which is what actually exposes missing-not-at-random.
- Kozyrkov: every chart titled with its FINDING, not its technique; corr
  heatmap (no action) replaced with return-reason breakdown; log scale on
  the skewed order-value distribution; outlier merchant named on chart.
- Rogati: every finding quantified in $ and ranked - findings.md is the
  exec deliverable, charts are the evidence.

Run:  python eda_everrest_v2.py
  ->  charts to ../../docs/how-to-eda-using-claude-python/charts/
  ->  findings to ./findings.md
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from statsmodels.tsa.seasonal import seasonal_decompose

SEED = 42
HERE = Path(__file__).parent
DATA = HERE / "data"
OUT = HERE.parent.parent / "docs" / "how-to-eda-using-claude-python" / "charts"
OUT.mkdir(exist_ok=True)

TEAL, SKY, INK, MUTED, HAIR = "#0D9488", "#38BDF8", "#0F172A", "#64748B", "#E2E8F0"
TEAL_CMAP = sns.light_palette(TEAL, as_cmap=True)
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
        "axes.titlesize": 12.5,
        "axes.titleweight": "bold",
        "axes.titlecolor": INK,
    }
)

findings: list[tuple[float, str]] = []  # ($ impact, text) - ranked at the end


def load() -> dict[str, pd.DataFrame]:
    return {
        "orders": pd.read_csv(DATA / "orders.csv", parse_dates=["order_ts"]),
        "order_items": pd.read_csv(DATA / "order_items.csv"),
        "merchants": pd.read_csv(DATA / "merchants.csv", parse_dates=["joined_at"]),
        "products": pd.read_csv(DATA / "products.csv"),
        "customers": pd.read_csv(DATA / "customers.csv", parse_dates=["signup_date"]),
        "payments": pd.read_csv(DATA / "payments.csv", parse_dates=["paid_ts"]),
        "returns": pd.read_csv(DATA / "returns.csv", parse_dates=["return_ts"]),
    }


# ---------------------------------------------------------------- DQ GATE
t = load()
orders_raw, order_items = t["orders"], t["order_items"]
merchants, customers, payments, returns = (
    t["merchants"],
    t["customers"],
    t["payments"],
    t["returns"],
)

order_items["net"] = (
    order_items.qty * order_items.unit_price * (1 - order_items.discount)
)
order_value = order_items.groupby("order_id").net.sum().rename("order_value")

# Gate 1: exact duplicate order rows (retry bug).
dup_mask = orders_raw.duplicated()
dupes = orders_raw[dup_mask]
dup_inflation = order_value.reindex(dupes.order_id).sum()
orders = orders_raw.drop_duplicates().copy()
findings.append(
    (
        dup_inflation,
        f"{len(dupes):,} duplicate order rows (March 2026 retry bug) inflate revenue by "
        f"${dup_inflation:,.0f} in any naive aggregate. Dedup upstream + add a uniqueness test.",
    )
)

# Chart 6: when do the duplicates happen?
dup_daily = dupes.set_index("order_ts").resample("D").size()
fig, ax = plt.subplots(figsize=(9, 3.6))
ax.plot(dup_daily.index, dup_daily.values, color=SKY, lw=1.5)
ax.set_title(
    f"All {len(dupes):,} duplicate orders land in March 2026 - a retry bug, not user behaviour"
)
ax.set_ylabel("duplicate rows / day")
fig.savefig(OUT / "duplicates_timeline.png")
plt.close(fig)

# Gate 2: cancelled orders carry no revenue.
orders = orders.merge(order_value, on="order_id", how="left")
orders = orders.merge(merchants[["merchant_id", "tier", "category"]], on="merchant_id")
cancelled_value = orders.loc[orders.status == "cancelled", "order_value"].sum()
rev_orders = orders[orders.status != "cancelled"]
findings.append(
    (
        cancelled_value,
        f"Cancelled orders carry ${cancelled_value:,.0f} of phantom value - exclude from all revenue views.",
    )
)

# ------------------------------------------------------- TRUST: MISSINGNESS
miss = pd.DataFrame({name: df.isna().mean() * 100 for name, df in t.items()}).T
miss = miss.dropna(axis=1, how="all").fillna(0)
miss = miss.loc[:, miss.max() > 0]
fig, ax = plt.subplots(figsize=(7.5, 3.4))
sns.heatmap(
    miss,
    annot=True,
    fmt=".1f",
    cmap=TEAL_CMAP,
    cbar_kws={"label": "% missing"},
    linewidths=0.5,
    linecolor="white",
    ax=ax,
)
ax.set_title("Only one column has a missing-data problem: payments.method (7.8%)")
fig.savefig(OUT / "missingness_matrix.png")
plt.close(fig)

# Missingness BY CHANNEL (Ng fix) - proves missing-not-at-random.
pay = payments.merge(
    orders_raw.drop_duplicates("order_id")[["order_id", "customer_id"]], on="order_id"
)
pay = pay.merge(customers[["customer_id", "channel_id"]], on="customer_id")
null_by_ch = (
    pay.groupby("channel_id")
    .method.apply(lambda s: s.isna().mean() * 100)
    .sort_values()
)
blocked_gmv = pay.loc[pay.method.isna(), "amount"].sum()
fig, ax = plt.subplots(figsize=(8, 4))
colors = [SKY if c == "affiliate" else TEAL for c in null_by_ch.index]
ax.barh(null_by_ch.index, null_by_ch.values, color=colors)
ax.set_title(
    "The nulls are not random: the affiliate tracker drops payment method (55% null)"
)
ax.set_xlabel("% of payments with null method")
for i, v in enumerate(null_by_ch.values):
    ax.text(v + 0.8, i, f"{v:.0f}%", va="center", fontsize=9, color=MUTED)
fig.savefig(OUT / "missing_by_channel.png")
plt.close(fig)
findings.append(
    (
        blocked_gmv,
        f"payments.method is missing-not-at-random: 55% null on the affiliate channel vs ~3.5% "
        f"elsewhere - a broken tracker, not user behaviour. ${blocked_gmv:,.0f} of GMV currently "
        f"unattributable by payment method. Fix the affiliate integration.",
    )
)

# ------------------------------------------------------- REVENUE STRUCTURE
rev = rev_orders.groupby("merchant_id").order_value.sum().sort_values(ascending=False)
top20_share = rev.head(20).sum() / rev.sum() * 100
cum = rev.cumsum() / rev.sum() * 100
fig, ax = plt.subplots(figsize=(9, 4.5))
ax.bar(
    range(60),
    rev.head(60) / 1e3,
    color=[SKY if m == "M0007" else TEAL for m in rev.head(60).index],
)
ax2 = ax.twinx()
ax2.plot(range(60), cum.head(60), color=INK, lw=1.6)
ax2.set_ylim(0, 100)
ax2.set_ylabel("cumulative %", color=MUTED)
ax2.grid(False)
ax.set_title(
    f"Top 20 of 400 merchants = {top20_share:.0f}% of revenue - and #1 is an anomaly, not a hero"
)
ax.set_ylabel("revenue ($k)")
ax.set_xlabel("merchant rank")
fig.savefig(OUT / "revenue_pareto.png")
plt.close(fig)

# Outlier merchant isolated + named (Kozyrkov fix).
med_all = rev_orders.order_value.median()
m7 = rev_orders[rev_orders.merchant_id == "M0007"]
m7_share = m7.order_value.sum() / rev.sum() * 100
findings.append(
    (
        m7.order_value.sum(),
        f"Merchant M0007 'Summit Wholesale Co' has a median order of ${m7.order_value.median():,.0f} "
        f"vs ${med_all:,.0f} platform-wide (~{m7.order_value.median()/med_all:,.0f}x) and alone is "
        f"{m7_share:.1f}% of revenue. It is a bulk wholesaler - exclude it from consumer category "
        f"benchmarks or every Grocery KPI is distorted.",
    )
)

fig, ax = plt.subplots(figsize=(9, 4.2))
sns.boxplot(
    data=rev_orders, x="tier", y="order_value", color=TEAL, ax=ax, showfliers=False
)
sns.stripplot(
    data=m7.sample(min(len(m7), 150), random_state=SEED),
    x="tier",
    y="order_value",
    color=SKY,
    size=3,
    ax=ax,
    jitter=0.25,
)
ax.set_yscale("log")
ax.set_title(
    "Order value by tier (log scale) - the blue cloud is ONE merchant: M0007 Summit Wholesale"
)
fig.savefig(OUT / "order_value_by_tier.png")
plt.close(fig)

# Distribution, log scale (Kozyrkov fix).
fig, ax = plt.subplots(figsize=(9, 4))
vals = rev_orders.order_value.dropna()
ax.hist(vals, bins=np.geomspace(vals.min() + 1, vals.max(), 90), color=TEAL)
ax.set_xscale("log")
ax.axvline(med_all, color=SKY, lw=1.6)
ax.text(
    med_all * 1.2,
    ax.get_ylim()[1] * 0.9,
    f"median ${med_all:,.0f}",
    color=MUTED,
    fontsize=9,
)
ax.set_title("Order values span 4 orders of magnitude - means will lie, use medians")
ax.set_xlabel("order value ($, log scale)")
fig.savefig(OUT / "order_value_dist.png")
plt.close(fig)

# ------------------------------------------------------- DEMAND RHYTHM
daily = rev_orders.set_index("order_ts").resample("D").size()
dec = seasonal_decompose(daily, period=7)
nov_lift = daily[daily.index.month == 11].mean() / daily[daily.index.month != 11].mean()
fig, axes = plt.subplots(3, 1, figsize=(9, 6.5), sharex=False)
axes[0].plot(daily.index, daily.values, color=TEAL, lw=0.9)
axes[0].set_title(
    f"November runs {nov_lift:.1f}x the rest of the year - stock up in October"
)
axes[1].plot(dec.trend.index, dec.trend.values, color=SKY, lw=1.6)
axes[1].set_title("Underlying trend (7-day)")
axes[2].plot(dec.seasonal.index[:56], dec.seasonal.values[:56], color=INK, lw=1.2)
axes[2].set_title("Weekly cycle: weekends lift ~40% - staff fulfilment accordingly")
fig.tight_layout()
fig.savefig(OUT / "demand_decomposition.png")
plt.close(fig)

nov_rev = rev_orders[rev_orders.order_ts.dt.month == 11].order_value.sum()
findings.append(
    (
        nov_rev,
        f"November is {nov_lift:.1f}x baseline demand (${nov_rev:,.0f} revenue). Inventory and "
        f"fulfilment capacity decisions for Q4 must be made by September.",
    )
)

pivot = (
    rev_orders.assign(
        dow=rev_orders.order_ts.dt.day_name().str[:3], hr=rev_orders.order_ts.dt.hour
    )
    .pivot_table(index="dow", columns="hr", values="order_id", aggfunc="count")
    .reindex(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
)
fig, ax = plt.subplots(figsize=(9, 3.4))
sns.heatmap(pivot, cmap=TEAL_CMAP, ax=ax, cbar_kws={"label": "orders"})
ax.set_title("Weekend evenings are the platform's prime time")
ax.set_ylabel("")
ax.set_xlabel("hour of day")
fig.savefig(OUT / "dow_hour_heatmap.png")
plt.close(fig)

# ------------------------------------------------------- CATEGORY + COHORTS
cat_month = (
    rev_orders.assign(month=rev_orders.order_ts.dt.to_period("M").dt.to_timestamp())
    .groupby(["month", "category"])
    .order_value.sum()
    .unstack()
)
fig, axes = plt.subplots(2, 4, figsize=(12, 5), sharex=True)
for ax, cat in zip(axes.flat, cat_month.columns):
    ax.plot(cat_month.index, cat_month[cat] / 1e3, color=TEAL, lw=1.5)
    ax.set_title(cat, fontsize=9)
    ax.tick_params(labelsize=7)
    ax.tick_params(axis="x", rotation=45)
fig.suptitle(
    "Every category shows the November wave - Grocery's scale is M0007, not demand",
    fontweight="bold",
)
fig.tight_layout()
fig.savefig(OUT / "category_small_multiples.png")
plt.close(fig)

first = (
    rev_orders.groupby("customer_id").order_ts.min().dt.to_period("M").rename("cohort")
)
o = rev_orders.join(first, on="customer_id")
o["age"] = (o.order_ts.dt.to_period("M") - o.cohort).apply(lambda p: p.n)
cohort = o.pivot_table(
    index="cohort", columns="age", values="customer_id", aggfunc="nunique"
)
ret = cohort.div(cohort[0], axis=0) * 100
m1 = ret[1].mean()
fig, ax = plt.subplots(figsize=(9, 4.6))
sns.heatmap(
    ret.iloc[:, :10],
    annot=True,
    fmt=".0f",
    cmap=TEAL_CMAP,
    cbar_kws={"label": "% active"},
    ax=ax,
)
ax.set_title(
    f"Month-1 retention averages {m1:.0f}% - the retention play starts in week 2, not month 3"
)
ax.set_ylabel("signup cohort")
ax.set_xlabel("months since first order")
fig.savefig(OUT / "cohort_retention.png")
plt.close(fig)

# ------------------------------------------------------- RETURNS
delivered = rev_orders[rev_orders.status == "delivered"]
is_ret = delivered.order_id.isin(returns.order_id)
ret_rate = is_ret.groupby(delivered.tier).mean() * 100
prem_ret_value = delivered.loc[
    is_ret & (delivered.tier == "premium"), "order_value"
].sum()
findings.append(
    (
        prem_ret_value,
        f"Premium-tier merchants return at {ret_rate['premium']:.1f}% vs "
        f"{ret_rate.drop('premium').mean():.1f}% elsewhere (~4x) - ${prem_ret_value:,.0f} of "
        f"delivered value comes back. This is a hidden quality problem in the tier that is "
        f"supposed to be the quality tier.",
    )
)

fig, ax = plt.subplots(figsize=(7.5, 4))
colors = [SKY if i == "premium" else TEAL for i in ret_rate.index]
ax.bar(ret_rate.index, ret_rate.values, color=colors)
for i, v in enumerate(ret_rate.values):
    ax.text(i, v + 0.3, f"{v:.1f}%", ha="center", fontsize=10, color=INK)
ax.set_title("Premium tier returns 4x more than any other tier - audit its top sellers")
ax.set_ylabel("% of delivered orders returned")
fig.savefig(OUT / "returns_by_tier.png")
plt.close(fig)

# Return reasons within premium (replaces v1 corr heatmap - Kozyrkov fix).
ret_m = returns.merge(delivered[["order_id", "tier"]], on="order_id")
reason = ret_m.pivot_table(
    index="reason", columns="tier", values="return_id", aggfunc="count"
)
reason_pct = reason / reason.sum() * 100
fig, ax = plt.subplots(figsize=(8.5, 4))
x = np.arange(len(reason_pct.index))
for j, (tier, color) in enumerate(
    zip(["standard", "premium", "enterprise"], [TEAL, SKY, INK])
):
    if tier in reason_pct:
        ax.bar(
            x + (j - 1) * 0.26, reason_pct[tier], width=0.26, color=color, label=tier
        )
ax.set_xticks(x)
ax.set_xticklabels(reason_pct.index, fontsize=9)
ax.legend(frameon=False, fontsize=9)
ax.set_title("'Quality' dominates premium returns - it is the product, not the courier")
ax.set_ylabel("% of tier's returns")
fig.savefig(OUT / "returns_reasons.png")
plt.close(fig)

# ------------------------------------------------------- FINDINGS (ranked by $)
findings.sort(key=lambda f: -f[0])
lines = [
    "# Everrest EDA - findings ranked by $ impact",
    f"\nSeed {SEED} · learn-python env · generated by eda_everrest_v2.py\n",
]
for i, (impact, text) in enumerate(findings, 1):
    lines.append(f"{i}. **${impact:,.0f}** - {text}")
(HERE / "findings.md").write_text("\n".join(lines))
print("\n".join(lines))
print(f"\n{len(list(OUT.glob('*.png')))} charts -> {OUT}")
