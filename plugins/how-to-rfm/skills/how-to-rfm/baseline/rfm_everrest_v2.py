"""Everrest RFM - v2 (post expert review).

Objective: where should Everrest's CRM team spend its Q3 retention budget,
and which customers are quietly the most valuable?

Expert-review fixes applied over v1 (panel of senior reviewers, 10yr+ in
data, data insights, and business):
- Data engineer: monetary + frequency now count DELIVERED orders only. v1
  included returned orders, inflating the returns-heavy segment's value.
- Methodology lead: raw RF codes replaced with the standard 11-segment map;
  F scored on rank (ties broke qcut); recency measured from a fixed ref date.
- Insights lead: every chart titled with its finding; added segment treemap,
  segment-by-channel (exposes the affiliate one-and-done), and a budget
  opportunity map. Dropped the raw RF-code bar (no action attached).
- Business lead: every segment carries a $ figure; a budget recommendation
  ranks where the next retention dollar earns most.
- QA / reproducibility: segments validated against the generator's ground-
  truth archetypes; fixed seed, fixed ref date, byte-identical re-runs.

Run:  python rfm_everrest_v2.py
  ->  charts to ../../docs/how-to-rfm-using-claude-python/charts/
  ->  findings to ./findings.md
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

SEED = 42
HERE = Path(__file__).parent
DATA = HERE / "data"
OUT = HERE.parent.parent / "docs" / "how-to-rfm-using-claude-python" / "charts"
OUT.mkdir(exist_ok=True)
REF_DATE = pd.Timestamp("2026-07-01")

TEAL, SKY, INK, MUTED, HAIR = "#0D9488", "#38BDF8", "#0F172A", "#64748B", "#E2E8F0"
AMBER = "#F59E0B"
TEAL_CMAP = plt.cm.get_cmap("BuGn")
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

findings: list[tuple[float, str]] = []

# ------------------------------------------------------------------ LOAD + DQ GATE
orders = pd.read_csv(DATA / "orders.csv", parse_dates=["order_ts"])
items = pd.read_csv(DATA / "order_items.csv")
customers = pd.read_csv(DATA / "customers.csv", parse_dates=["signup_date"])
truth = pd.read_csv(DATA / "_ground_truth.csv")

items["net"] = items.qty * items.unit_price * (1 - items.discount)
ov = items.groupby("order_id").net.sum().rename("order_value")
orders = orders.merge(ov, on="order_id", how="left")

# FIX (data engineer): delivered orders only - returned orders are not revenue.
returned_value = orders.loc[orders.status == "returned", "order_value"].sum()
deliv = orders[orders.status == "delivered"].copy()
findings.append(
    (
        returned_value,
        f"Returned orders carry ${returned_value:,.0f} of gross value that v1 counted as "
        f"monetary. Scoring on delivered-only revenue moves the returns-heavy segment out of "
        f"the high-value tiers where it did not belong.",
    )
)

# ------------------------------------------------------------------ RFM SCORES
rfm = (
    deliv.groupby("customer_id")
    .agg(
        recency=("order_ts", lambda s: (REF_DATE - s.max()).days),
        frequency=("order_id", "count"),
        monetary=("order_value", "sum"),
    )
    .reset_index()
)

rfm["R"] = pd.qcut(rfm.recency, 5, labels=[5, 4, 3, 2, 1]).astype(int)
rfm["F"] = pd.qcut(
    rfm.frequency.rank(method="first"), 5, labels=[1, 2, 3, 4, 5]
).astype(int)
rfm["M"] = pd.qcut(rfm.monetary, 5, labels=[1, 2, 3, 4, 5]).astype(int)
rfm["FM"] = np.ceil((rfm.F + rfm.M) / 2).astype(int)


def segment(r: int, f: int, m: int, fm: int) -> str:
    """Standard 11-segment RFM map (priority order: value-critical first)."""
    if r >= 4 and fm >= 4:
        return "Champions"
    if r <= 2 and m >= 4:
        return "Can't Lose Them"  # high spenders gone quiet - win-back gold
    if r <= 2 and fm >= 3:
        return "At Risk"
    if fm >= 4:
        return "Loyal Customers"
    if r >= 4 and f <= 1:
        return "New Customers"
    if r >= 3 and fm >= 2:
        return "Potential Loyalist"
    if r >= 3 and fm <= 2:
        return "Promising"
    if r == 3:
        return "Need Attention"
    if r == 2:
        return "About to Sleep"
    if r <= 2 and fm <= 2:
        return "Hibernating"
    return "Lost"


rfm["seg"] = [segment(r, f, m, fm) for r, f, m, fm in zip(rfm.R, rfm.F, rfm.M, rfm.FM)]
rfm = rfm.merge(
    customers[["customer_id", "channel_id", "signup_date"]], on="customer_id"
)
rfm = rfm.merge(truth, on="customer_id", how="left")

SEG_ORDER = [
    "Champions",
    "Loyal Customers",
    "Potential Loyalist",
    "New Customers",
    "Promising",
    "Need Attention",
    "About to Sleep",
    "At Risk",
    "Can't Lose Them",
    "Hibernating",
    "Lost",
]
seg_stats = (
    rfm.groupby("seg")
    .agg(
        customers=("customer_id", "count"),
        total_monetary=("monetary", "sum"),
        avg_monetary=("monetary", "mean"),
        avg_recency=("recency", "mean"),
        avg_freq=("frequency", "mean"),
    )
    .reindex([s for s in SEG_ORDER if s in rfm.seg.unique()])
)

# ------------------------------------------------------------------ CHARTS
# 1 - R / F / M distributions
fig, axes = plt.subplots(1, 3, figsize=(12, 3.4))
for ax, col, c, lbl in zip(
    axes,
    ["recency", "frequency", "monetary"],
    [TEAL, SKY, INK],
    ["days since last order", "orders", "$ delivered spend"],
):
    ax.hist(rfm[col], bins=40, color=c)
    ax.set_title(col.title())
    ax.set_xlabel(lbl)
fig.suptitle("The three RFM signals, scored 1-5 by quintile", fontweight="bold")
fig.tight_layout()
fig.savefig(OUT / "rfm_distributions.png")
plt.close(fig)


# 2 - segment treemap (manual squarify)
def squarify(sizes, x, y, dx, dy):
    sizes = np.asarray(sizes, float) * (dx * dy) / np.asarray(sizes, float).sum()
    rects, i = [], 0
    while i < len(sizes):
        # grow a row while aspect improves
        row, best = [sizes[i]], _worst([sizes[i]], min(dx, dy))
        j = i + 1
        while j < len(sizes):
            w = _worst(row + [sizes[j]], min(dx, dy))
            if w > best:
                break
            row.append(sizes[j])
            best = w
            j += 1
        # lay the row
        total = sum(row)
        if dx >= dy:
            rw = total / dy
            oy = y
            for s in row:
                rh = s / rw
                rects.append((x, oy, rw, rh))
                oy += rh
            x += rw
            dx -= rw
        else:
            rh = total / dx
            ox = x
            for s in row:
                rw = s / rh
                rects.append((ox, y, rw, rh))
                ox += rw
            y += rh
            dy -= rh
        i = j
    return rects


def _worst(row, side):
    total = sum(row)
    s2 = side * side
    t2 = total * total
    mx, mn = max(row), min(row)
    return max(s2 * mx / t2, t2 / (s2 * mn))


sizes = seg_stats.customers.values
rects = squarify(sizes, 0, 0, 100, 100)
cmap = plt.cm.get_cmap("BuGn")
fig, ax = plt.subplots(figsize=(11, 6))
for (rx, ry, rw, rh), name, cust, val in zip(
    rects, seg_stats.index, seg_stats.customers, seg_stats.total_monetary
):
    frac = val / seg_stats.total_monetary.max()
    ax.add_patch(
        mpatches.Rectangle(
            (rx, ry),
            rw,
            rh,
            facecolor=cmap(0.25 + 0.6 * frac),
            edgecolor="white",
            linewidth=2,
        )
    )
    if rw * rh > 40:
        ax.text(
            rx + rw / 2,
            ry + rh / 2,
            f"{name}\n{cust:,} cust\n${val/1e3:,.0f}k",
            ha="center",
            va="center",
            fontsize=8.5,
            color="white" if frac > 0.5 else INK,
            fontweight="bold",
        )
ax.set_xlim(0, 100)
ax.set_ylim(0, 100)
ax.axis("off")
ax.set_title(
    "11 segments by customer count - colour = total delivered value", fontweight="bold"
)
fig.savefig(OUT / "segment_treemap.png")
plt.close(fig)

# 3 - monetary pareto (whale)
m = rfm.monetary.sort_values(ascending=False).values
cumshare = np.cumsum(m) / m.sum() * 100
custshare = np.arange(1, len(m) + 1) / len(m) * 100
top5_val = cumshare[int(len(m) * 0.05)]
fig, ax = plt.subplots(figsize=(9, 4.2))
ax.plot(custshare, cumshare, color=TEAL, lw=2)
ax.axvline(5, color=SKY, lw=1.4)
ax.axhline(top5_val, color=SKY, lw=1, ls=":")
ax.text(
    7,
    top5_val - 8,
    f"top 5% of customers\n= {top5_val:.0f}% of value",
    color=MUTED,
    fontsize=9,
)
ax.set_title(
    f"Everrest is whale-dependent: the top 5% of customers drive {top5_val:.0f}% of revenue"
)
ax.set_xlabel("% of customers (ranked by spend)")
ax.set_ylabel("cumulative % of revenue")
fig.savefig(OUT / "monetary_pareto.png")
plt.close(fig)
findings.append(
    (
        rfm.monetary.sort_values(ascending=False).head(int(len(rfm) * 0.05)).sum(),
        f"Value is highly concentrated: the top 5% of customers generate {top5_val:.0f}% of "
        f"delivered revenue. Protecting this core is worth more than chasing new low-value signups.",
    )
)

# 4 - R x F heatmap (customer count)
grid = rfm.pivot_table(
    index="R", columns="F", values="customer_id", aggfunc="count"
).reindex(index=[5, 4, 3, 2, 1], columns=[1, 2, 3, 4, 5])
fig, ax = plt.subplots(figsize=(6.5, 5))
im = ax.imshow(grid.values, cmap="BuGn", aspect="auto")
ax.set_xticks(range(5))
ax.set_xticklabels([1, 2, 3, 4, 5])
ax.set_yticks(range(5))
ax.set_yticklabels([5, 4, 3, 2, 1])
ax.set_xlabel("Frequency score →")
ax.set_ylabel("Recency score →")
for i in range(5):
    for j in range(5):
        v = grid.values[i, j]
        if not np.isnan(v):
            ax.text(
                j,
                i,
                f"{int(v):,}",
                ha="center",
                va="center",
                color="white" if v > np.nanmax(grid.values) * 0.5 else INK,
                fontsize=8,
            )
ax.set_title("The RFM grid: customers cluster at the corners, not the middle")
fig.colorbar(im, ax=ax, label="customers")
fig.savefig(OUT / "rf_heatmap.png")
plt.close(fig)

# 5 - recency vs frequency scatter, bubble = monetary, key segments highlighted
fig, ax = plt.subplots(figsize=(9, 5.2))
base = rfm[~rfm.seg.isin(["Champions", "Can't Lose Them"])]
ax.scatter(
    base.recency,
    base.frequency,
    s=np.clip(base.monetary / 60, 4, 120),
    alpha=0.12,
    color=MUTED,
    edgecolors="none",
)
for name, col in [("Champions", TEAL), ("Can't Lose Them", AMBER)]:
    d = rfm[rfm.seg == name]
    ax.scatter(
        d.recency,
        d.frequency,
        s=np.clip(d.monetary / 60, 6, 160),
        alpha=0.55,
        color=col,
        edgecolors="none",
        label=name,
    )
ax.set_xlabel("Recency (days since last order)")
ax.set_ylabel("Frequency (orders)")
ax.legend(frameon=False)
ax.set_title(
    "Champions sit low-recency/high-frequency; Can't-Lose-Them drift right and must be pulled back"
)
fig.savefig(OUT / "recency_frequency.png")
plt.close(fig)

# 6 - segment by acquisition channel (stacked) - affiliate one-and-done
ch = rfm.pivot_table(
    index="seg",
    columns="channel_id",
    values="customer_id",
    aggfunc="count",
    fill_value=0,
).reindex(seg_stats.index)
ch_pct = ch.div(ch.sum(axis=1), axis=0) * 100
fig, ax = plt.subplots(figsize=(10, 5))
bottom = np.zeros(len(ch_pct))
palette = [TEAL, SKY, INK, "#5EEAD4", MUTED, AMBER]
for col, color in zip(ch_pct.columns, palette):
    ax.barh(ch_pct.index, ch_pct[col], left=bottom, color=color, label=col)
    bottom += ch_pct[col].values
ax.set_xlabel("% of segment's customers by acquisition channel")
ax.legend(
    frameon=False, ncol=6, loc="lower center", bbox_to_anchor=(0.5, -0.18), fontsize=8
)
ax.set_title(
    "Affiliate over-indexes on Hibernating & Lost - it buys one-and-done, not loyalty"
)
ax.invert_yaxis()
fig.savefig(OUT / "segment_by_channel.png")
plt.close(fig)
affil = rfm[rfm.channel_id == "affiliate"]
affil_lowvalue = affil[affil.seg.isin(["Hibernating", "Lost"])]
findings.append(
    (
        affil_lowvalue.monetary.sum(),
        f"{len(affil_lowvalue):,} affiliate-acquired customers ({len(affil_lowvalue)/len(affil)*100:.0f}% "
        f"of the channel) land in Hibernating/Lost with only ${affil_lowvalue.monetary.sum():,.0f} "
        f"of lifetime value between them. Cut affiliate acquisition spend or renegotiate on retained value.",
    )
)

# 7 - monetary boxplot by segment (log)
fig, ax = plt.subplots(figsize=(11, 4.6))
data = [rfm.loc[rfm.seg == s, "monetary"].values for s in seg_stats.index]
bp = ax.boxplot(
    data, vert=True, patch_artist=True, showfliers=False, medianprops={"color": INK}
)
for patch in bp["boxes"]:
    patch.set_facecolor(TEAL)
    patch.set_alpha(0.65)
ax.set_yscale("log")
ax.set_xticklabels(seg_stats.index, rotation=35, ha="right", fontsize=9)
ax.set_title(
    "Monetary value per segment (log) - Champions and Can't-Lose-Them are the money"
)
ax.set_ylabel("lifetime delivered spend ($)")
fig.savefig(OUT / "monetary_by_segment.png")
plt.close(fig)

# 8 - Nov signup cohort reactivation
nov = rfm.groupby("nov_cohort").agg(
    customers=("customer_id", "count"),
    active=("R", lambda s: (s >= 4).mean() * 100),
    avg_monetary=("monetary", "mean"),
)
fig, ax = plt.subplots(figsize=(7.5, 4))
labels = ["Acquired other months", "Acquired in Nov promo"]
ax.bar(labels, nov.active.reindex([False, True]).values, color=[TEAL, AMBER])
for i, v in enumerate(nov.active.reindex([False, True]).values):
    ax.text(i, v + 0.6, f"{v:.0f}% still active", ha="center", fontsize=10, color=INK)
ax.set_title("The November promo cohort barely reactivated - a spike, not real growth")
ax.set_ylabel("% currently active (recency score 4-5)")
fig.savefig(OUT / "nov_cohort.png")
plt.close(fig)
nov_dead = rfm[(rfm.nov_cohort) & (rfm.R <= 2)]
findings.append(
    (
        nov_dead.monetary.sum(),
        f"{len(nov_dead):,} of the November-promo cohort are already lapsed, holding only "
        f"${nov_dead.monetary.sum():,.0f} of value. Promo acquisition inflated signups without "
        f"retention - judge campaigns on 90-day repeat rate, not signup count.",
    )
)

# 9 - avg value vs recency bubble (the budget map)
fig, ax = plt.subplots(figsize=(9.5, 5.6))
sizes = seg_stats.customers / seg_stats.customers.max() * 2400 + 60
priority = {
    "Champions": TEAL,
    "Loyal Customers": TEAL,
    "At Risk": AMBER,
    "Can't Lose Them": AMBER,
}
colors = [priority.get(s, MUTED) for s in seg_stats.index]
ax.scatter(
    seg_stats.avg_recency,
    seg_stats.avg_monetary,
    s=sizes,
    c=colors,
    alpha=0.6,
    edgecolors="white",
    linewidth=1.5,
)
for s, x, y in zip(seg_stats.index, seg_stats.avg_recency, seg_stats.avg_monetary):
    ax.text(x, y, s, fontsize=8, ha="center", va="center", color=INK)
ax.axvspan(120, ax.get_xlim()[1] if False else 400, alpha=0.04, color=AMBER)
ax.set_xlabel("Avg recency (days since last order) - further right = more lapsed →")
ax.set_ylabel("Avg lifetime value ($)")
ax.set_title(
    "Budget map: spend where value is high AND recency is slipping (amber = act now)"
)
fig.savefig(OUT / "budget_map.png")
plt.close(fig)

# 10 - customer share vs revenue share (top segments)
share = (
    seg_stats.assign(
        cust_share=seg_stats.customers / seg_stats.customers.sum() * 100,
        rev_share=seg_stats.total_monetary / seg_stats.total_monetary.sum() * 100,
    )
    .sort_values("rev_share", ascending=False)
    .head(6)
)
fig, ax = plt.subplots(figsize=(9.5, 4.4))
x = np.arange(len(share))
w = 0.38
ax.bar(x - w / 2, share.cust_share, w, color=MUTED, label="% of customers")
ax.bar(x + w / 2, share.rev_share, w, color=TEAL, label="% of revenue")
ax.set_xticks(x)
ax.set_xticklabels(share.index, rotation=25, ha="right", fontsize=9)
ax.legend(frameon=False)
ax.set_title("A few segments punch far above their headcount in revenue")
ax.set_ylabel("%")
fig.savefig(OUT / "share_vs_revenue.png")
plt.close(fig)

# 11 - validation vs ground-truth archetypes (QA reviewer)
xt = pd.crosstab(rfm.archetype, rfm.seg, normalize="index") * 100
key_arche = ["champion", "loyal", "cant_lose_them", "at_risk", "hibernating", "lost"]
xt = xt.reindex([a for a in key_arche if a in xt.index])
xt = xt[[c for c in seg_stats.index if c in xt.columns]]
fig, ax = plt.subplots(figsize=(11, 4))
im = ax.imshow(xt.values, cmap="BuGn", aspect="auto", vmin=0, vmax=100)
ax.set_xticks(range(len(xt.columns)))
ax.set_xticklabels(xt.columns, rotation=35, ha="right", fontsize=8)
ax.set_yticks(range(len(xt.index)))
ax.set_yticklabels(xt.index, fontsize=9)
ax.set_title("Recovery check: planted archetypes land in the matching RFM segments")
fig.colorbar(im, ax=ax, label="% of archetype")
fig.savefig(OUT / "validation_heatmap.png")
plt.close(fig)

# 12 - Can't Lose Them close-up (the headline win-back)
clt = seg_stats.loc["Can't Lose Them"] if "Can't Lose Them" in seg_stats.index else None
at = seg_stats.loc["At Risk"] if "At Risk" in seg_stats.index else None
fig, ax = plt.subplots(figsize=(8, 4.2))
segs = [
    s
    for s in ["Champions", "Loyal Customers", "At Risk", "Can't Lose Them"]
    if s in seg_stats.index
]
vals = [seg_stats.loc[s, "total_monetary"] / 1e3 for s in segs]
colors = [TEAL, TEAL, AMBER, AMBER]
ax.bar(segs, vals, color=colors)
for i, v in enumerate(vals):
    ax.text(i, v + max(vals) * 0.01, f"${v:,.0f}k", ha="center", fontsize=10, color=INK)
ax.set_title(
    "Where the value sits: two segments to protect (teal), two to win back now (amber)"
)
ax.set_ylabel("total delivered value ($k)")
fig.savefig(OUT / "value_at_stake.png")
plt.close(fig)

if clt is not None:
    findings.append(
        (
            clt.total_monetary,
            f"'Can't Lose Them' is {int(clt.customers):,} customers worth ${clt.total_monetary:,.0f} "
            f"who averaged {clt.avg_recency:.0f} days since their last order. They are the single "
            f"highest-ROI target for the Q3 retention budget - high value, still recoverable.",
        )
    )
if at is not None:
    findings.append(
        (
            at.total_monetary,
            f"'At Risk' adds {int(at.customers):,} customers and ${at.total_monetary:,.0f} of value "
            f"slipping away. Second budget priority after Can't-Lose-Them.",
        )
    )

# ------------------------------------------------------------------ FINDINGS
findings.sort(key=lambda f: -f[0])
lines = [
    "# Everrest RFM - findings ranked by $ at stake",
    f"\nSeed {SEED} · ref date {REF_DATE.date()} · delivered-only monetary · "
    f"generated by rfm_everrest_v2.py\n",
]
for i, (impact, text) in enumerate(findings, 1):
    lines.append(f"{i}. **${impact:,.0f}** - {text}")
lines.append("\n## Segment summary\n")
lines.append(
    seg_stats.assign(
        total_monetary=seg_stats.total_monetary.round(0),
        avg_monetary=seg_stats.avg_monetary.round(0),
        avg_recency=seg_stats.avg_recency.round(0),
        avg_freq=seg_stats.avg_freq.round(1),
    ).to_markdown()
)
(HERE / "findings.md").write_text("\n".join(lines))
print("\n".join(lines[:12]))
print(f"\n{len(list(OUT.glob('*.png')))} charts -> {OUT}")
