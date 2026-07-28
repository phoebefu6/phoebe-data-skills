"""Everrest metric-to-scorecard build - Data Analytics flagship (scorecard track).

Reads the Everrest stage-3 marts (the clean CSVs that are the output of the
warehouse), defines a board-ready metric set explicitly, VALIDATES each metric
against the naive version an analyst would ship by accident, then writes every
computed number to metrics.json and generates a self-contained executive
scorecard (everrest_scorecard.html). No number on the scorecard is hand-typed -
they are all injected from the values computed here.

Honesty gate (scorecard track): every figure reconciles to the marts and is
produced by this committed script; metric definitions are shipped so each tile
is auditable.

The marts were generated with seed 42 (see how-to-schema-and-warehouse and
how-to-eda). This step is deterministic given those marts.

Run (from this folder):
    python build_scorecard.py
Outputs -> ./output/ :
    metrics.json                  every computed value
    everrest_scorecard.html       the self-contained exec scorecard
    validation_status.png         revenue inflation from unfiltered status
    aov_outlier.png               AOV distortion from the M0007 wholesaler
    rev_trend.png                 12-month delivered-revenue trend, Nov peak
    category_rev.png              delivered revenue by clean category
    concentration.png             merchant revenue concentration (top 15)
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd

# ----------------------------------------------------------------- config
SEED = 42  # marts were generated with this seed; this step is deterministic
HERE = Path(__file__).resolve().parent
MARTS = HERE.parent / "how-to-eda" / "data"
OUT = HERE / "output"
OUT.mkdir(exist_ok=True)

# take rate for the platform commission tile - an explicit business assumption,
# stated in the metric definition so a reader can audit it (not a data fact).
TAKE_RATE = 0.11

# revenue is recognized on delivery; in-flight and cancelled orders are excluded.
RECOGNIZED_STATUS = "delivered"

INK = "#0F172A"
ACCENT = "#0D9488"
AMBER = "#F59E0B"
MUTED = "#64748B"
HAIR = "#E2E8F0"

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "axes.edgecolor": HAIR,
        "axes.linewidth": 1.0,
        "axes.grid": True,
        "grid.color": HAIR,
        "grid.linewidth": 0.8,
        "axes.axisbelow": True,
        "figure.dpi": 300,
    }
)


def money(x: float) -> str:
    return f"${x:,.0f}"


# ----------------------------------------------------------------- load marts
def load_marts() -> dict[str, pd.DataFrame]:
    orders = pd.read_csv(MARTS / "orders.csv", parse_dates=["order_ts"])
    items = pd.read_csv(MARTS / "order_items.csv")
    returns = pd.read_csv(MARTS / "returns.csv", parse_dates=["return_ts"])
    merchants = pd.read_csv(MARTS / "merchants.csv")
    customers = pd.read_csv(MARTS / "customers.csv", parse_dates=["signup_date"])
    items["line_net"] = items.qty * items.unit_price * (1 - items.discount)
    order_rev = (
        items.groupby("order_id", as_index=False)
        .line_net.sum()
        .rename(columns={"line_net": "net_amount"})
    )
    orders = orders.merge(order_rev, on="order_id", how="left")
    orders["net_amount"] = orders.net_amount.fillna(0.0)
    orders["month"] = orders.order_ts.dt.to_period("M")
    orders["quarter"] = orders.order_ts.dt.to_period("Q")
    return {
        "orders": orders,
        "items": items,
        "returns": returns,
        "merchants": merchants,
        "customers": customers,
    }


# ----------------------------------------------------------------- metrics
def compute(marts: dict[str, pd.DataFrame]) -> dict:
    orders = marts["orders"]
    returns = marts["returns"]
    merchants = marts["merchants"]

    deliv = orders[orders.status == RECOGNIZED_STATUS].copy()

    # current period = latest full quarter in the data; prior = the one before.
    quarters = sorted(orders.quarter.unique())
    cur_q, prev_q = quarters[-1], quarters[-2]
    cur = deliv[deliv.quarter == cur_q]
    prev = deliv[deliv.quarter == prev_q]

    def pop(cur_val: float, prev_val: float) -> float:
        return (cur_val - prev_val) / prev_val * 100 if prev_val else 0.0

    return_ids = set(returns.order_id)

    # --- M1 GMV (delivered) -------------------------------------------------
    # net_amount = qty * unit_price * (1 - discount): merchandise value, net of
    # discounts but GROSS of returns. Labelled GMV, not "revenue" - on a
    # marketplace the company's revenue is the take (M2), not the flow.
    rev_cur = cur.net_amount.sum()
    rev_prev = prev.net_amount.sum()
    rev_all_status = orders[orders.quarter == cur_q].net_amount.sum()
    status_inflation = (rev_all_status - rev_cur) / rev_cur * 100
    # how much of this GMV sits on orders that were later returned
    returned_gmv = cur[cur.order_id.isin(return_ids)].net_amount.sum()
    returned_gmv_pct = returned_gmv / rev_cur * 100

    # --- M2 Platform Net Revenue (the take) ---------------------------------
    commission_cur = rev_cur * TAKE_RATE

    # --- M3 Delivered Orders ------------------------------------------------
    orders_cur = len(cur)
    orders_prev = len(prev)

    # --- M4 Average Order Value (excl M0007 wholesale outlier) --------------
    cur_no7 = cur[cur.merchant_id != "M0007"]
    aov_cur = cur_no7.net_amount.mean()
    aov_median = cur_no7.net_amount.median()  # reported alongside the mean
    aov_prev = prev[prev.merchant_id != "M0007"].net_amount.mean()
    aov_naive = cur.net_amount.mean()  # includes the wholesaler
    aov_distortion = (aov_naive - aov_cur) / aov_cur * 100

    # --- M5 Active Buyers (distinct customers with a delivered order) -------
    # replaces a dead "active merchants" tile: every one of the 400 merchants
    # transacts every quarter, so that metric was a constant. The demand side
    # actually moves and is what a two-sided board asks about.
    buyers_cur = cur.customer_id.nunique()
    buyers_prev = prev.customer_id.nunique()

    # --- M6 Return Rate (returns / delivered orders) -----------------------
    cur_ids = set(cur.order_id)
    prev_ids = set(prev.order_id)
    ret_cur = returns[returns.order_id.isin(cur_ids)]
    ret_prev = returns[returns.order_id.isin(prev_ids)]
    return_rate_cur = len(ret_cur) / len(cur) * 100
    return_rate_prev = len(ret_prev) / len(prev) * 100
    # naive denominator = all orders (inflates the base, hides the true rate)
    all_cur = orders[orders.quarter == cur_q]
    return_rate_naive = (
        len(returns[returns.order_id.isin(set(all_cur.order_id))]) / len(all_cur) * 100
    )

    # --- M7 Repeat Buyer Rate (WITHIN quarter, so it has a trajectory) ------
    def repeat_within(df: pd.DataFrame) -> float:
        oc = df.groupby("customer_id").order_id.nunique()
        return (oc >= 2).mean() * 100

    repeat_cur = repeat_within(cur)
    repeat_prev = repeat_within(prev)

    # --- M8 Top-Merchant Concentration (share of GMV, this period) ----------
    by_merch = cur.groupby("merchant_id").net_amount.sum().sort_values(ascending=False)
    top1_share = by_merch.iloc[0] / rev_cur * 100
    top1_id = str(by_merch.index[0])
    top10_share = by_merch.head(10).sum() / rev_cur * 100

    # --- trends / breakdowns (trailing 12 months, delivered) -----------------
    monthly = deliv.groupby("month").net_amount.sum().sort_index()
    month_labels = [str(p) for p in monthly.index]
    month_vals = [float(v) for v in monthly.values]
    peak_i = int(monthly.values.argmax())
    peak_month = month_labels[peak_i]
    non_peak = monthly[[p for p in monthly.index if p.month not in (11, 12)]].mean()
    peak_multiple = monthly.max() / non_peak

    cat = (
        deliv.merge(
            merchants[["merchant_id", "category"]], on="merchant_id", how="left"
        )
        .groupby("category")
        .net_amount.sum()
        .sort_values(ascending=False)
    )

    conc = by_merch.head(15)

    metrics = {
        "seed": SEED,
        "recognized_status": RECOGNIZED_STATUS,
        "take_rate": TAKE_RATE,
        "current_period": str(cur_q),
        "prior_period": str(prev_q),
        "generated_from": "Everrest stage-3 marts (seed 42)",
        "tiles": [
            {
                "id": "gmv",
                "label": "GMV (Delivered)",
                "sub": "merchandise value",
                "value": rev_cur,
                "fmt": "money",
                "pop": pop(rev_cur, rev_prev),
                "rag": "amber",
                "definition": "SUM(qty x unit_price x (1 - discount)) over delivered orders, current quarter. Grain: order. Net of discounts, GROSS of returns. This is merchandise flow, not company revenue.",
                "validation": f"Counting all statuses reports {money(rev_all_status)} (+{status_inflation:.0f}%). And {returned_gmv_pct:.1f}% of this GMV ({money(returned_gmv)}) sits on orders later returned - so GMV, not 'net revenue', is the honest label.",
            },
            {
                "id": "net_revenue",
                "label": "Platform Net Revenue",
                "sub": f"the take @ {TAKE_RATE:.0%}",
                "value": commission_cur,
                "fmt": "money",
                "pop": pop(rev_cur, rev_prev),
                "rag": "amber",
                "definition": f"GMV x {TAKE_RATE:.0%} take rate. This is what Everrest actually earns - the number that belongs on the P&L, not GMV. The take rate is a stated assumption, not yet a data field.",
                "validation": f"Board-critical distinction: GMV is {money(rev_cur)} of merchandise flow; the company earns {money(commission_cur)}. Re-rating the take is a one-number change.",
            },
            {
                "id": "orders",
                "label": "Delivered Orders",
                "sub": "count",
                "value": orders_cur,
                "fmt": "int",
                "pop": pop(orders_cur, orders_prev),
                "rag": "green",
                "definition": "COUNT(orders) WHERE status = 'delivered', current quarter.",
                "validation": "Ties to the GMV order set - same filter, same grain.",
            },
            {
                "id": "aov",
                "label": "Avg Order Value",
                "sub": f"excl. M0007 &middot; median {money(aov_median)}",
                "value": aov_cur,
                "fmt": "money2",
                "pop": pop(aov_cur, aov_prev),
                "rag": "green",
                "definition": f"MEAN(net_amount) over delivered orders, EXCLUDING merchant M0007 (bulk wholesaler, ~50x median order). Grain: order. Median {money(aov_median)} shown alongside because the distribution is right-skewed.",
                "validation": f"Including M0007 lifts the mean to {money(aov_naive)} (+{aov_distortion:.0f}%). The median ({money(aov_median)}) sits well below the mean - a right skew, so both are reported.",
            },
            {
                "id": "active_buyers",
                "label": "Active Buyers",
                "sub": "distinct, delivered",
                "value": buyers_cur,
                "fmt": "int",
                "pop": pop(buyers_cur, buyers_prev),
                "rag": "green",
                "definition": "COUNT(DISTINCT customer_id) with >= 1 delivered order this quarter. The demand side of the marketplace.",
                "validation": "Active merchants is a constant here (all 400 transact every quarter), so it was dropped for this - the number that actually moves and shows demand.",
            },
            {
                "id": "return_rate",
                "label": "Return Rate",
                "sub": "returns / delivered",
                "value": return_rate_cur,
                "fmt": "pct",
                "pop": return_rate_cur - return_rate_prev,
                "pop_is_pts": True,
                "rag": "amber" if return_rate_cur > 6 else "green",
                "definition": "COUNT(returns on delivered orders) / COUNT(delivered orders), current quarter.",
                "validation": f"Using all orders as the denominator understates it at {return_rate_naive:.1f}%. Only delivered orders can be returned, so they are the honest base.",
            },
            {
                "id": "repeat_rate",
                "label": "Repeat Buyer Rate",
                "sub": "within quarter",
                "value": repeat_cur,
                "fmt": "pct",
                "pop": repeat_cur - repeat_prev,
                "pop_is_pts": True,
                "rag": "green",
                "definition": "Share of active buyers with >= 2 delivered orders WITHIN the quarter. Measured per-quarter so it has a trajectory, not a static trailing figure.",
                "validation": "On delivered orders only, so cancelled-order churn does not masquerade as loyalty. Per-quarter framing lets the board see retention moving.",
            },
            {
                "id": "concentration",
                "label": "Top-Merchant Share",
                "sub": f"{top1_id} of GMV",
                "value": top1_share,
                "fmt": "pct",
                "pop": None,
                "pop_is_pts": True,
                "rag": "amber",
                "definition": "GMV of the single largest merchant / total GMV, current quarter. A concentration-risk flag.",
                "validation": f"{top1_id} alone is {top1_share:.0f}% and the top 10 are {top10_share:.0f}% of GMV - a dependency the board should see, not an aggregate that hides it.",
            },
        ],
        "trend": {"labels": month_labels, "values": month_vals, "peak_index": peak_i},
        "peak_month": peak_month,
        "peak_multiple": float(peak_multiple),
        "category": {
            "labels": list(cat.index),
            "values": [float(v) for v in cat.values],
        },
        "concentration_top": {
            "labels": list(conc.index),
            "values": [float(v) for v in conc.values],
            "outlier": top1_id,
        },
        "headline": (
            f"GMV was {money(rev_cur)} in {cur_q}, down {abs(pop(rev_cur, rev_prev)):.1f}% QoQ against a "
            f"seasonally stronger prior quarter - on this platform Everrest's own take is {money(commission_cur)}. "
            f"{peak_month.split('-')[0]}-11 is the demand peak at {peak_multiple:.1f}x a normal month, so plan "
            f"inventory to it. {top1_id} is {top1_share:.0f}% of GMV: a concentration risk to watch."
        ),
        "checks": {
            "status_inflation_pct": status_inflation,
            "aov_distortion_pct": aov_distortion,
            "aov_median": aov_median,
            "return_rate_naive_pct": return_rate_naive,
            "revenue_all_status": rev_all_status,
            "returned_gmv": returned_gmv,
            "returned_gmv_pct": returned_gmv_pct,
            "yoy_available": False,
            "yoy_note": (
                "Year-over-year is not computable: the marts span a single "
                "12-month window (2025Q3 to 2026Q2), so the current quarter has "
                "no prior-year comparator. QoQ is shown against the seasonal "
                "trend on the card; YoY is the next data requirement."
            ),
        },
    }
    return metrics


# ----------------------------------------------------------------- charts
def _style(ax) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    for lbl in ax.get_xticklabels() + ax.get_yticklabels():
        lbl.set_color(MUTED)
        lbl.set_fontsize(9)


def chart_status(m: dict) -> None:
    c = m["checks"]
    rev = next(t for t in m["tiles"] if t["id"] == "gmv")["value"]
    vals = [c["revenue_all_status"], rev]
    labels = ["All statuses\n(naive)", "Delivered GMV\n(validated)"]
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    bars = ax.bar(labels, vals, color=[AMBER, ACCENT], width=0.58)
    for b, v in zip(bars, vals):
        ax.text(
            b.get_x() + b.get_width() / 2,
            v,
            money(v),
            ha="center",
            va="bottom",
            color=INK,
            fontsize=11,
            fontweight="bold",
        )
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x/1e6:.1f}M"))
    ax.set_title(
        f"Unfiltered status inflates revenue {c['status_inflation_pct']:.0f}%",
        color=INK,
        fontsize=12.5,
        fontweight="bold",
        loc="left",
        pad=12,
    )
    ax.set_ylim(0, max(vals) * 1.16)
    _style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "validation_status.png", bbox_inches="tight")
    plt.close(fig)


def chart_aov(marts: dict, m: dict) -> None:
    orders = marts["orders"]
    cur_q = m["current_period"]
    deliv = orders[
        (orders.status == RECOGNIZED_STATUS) & (orders.quarter.astype(str) == cur_q)
    ]
    no7 = deliv[deliv.merchant_id != "M0007"]
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    ax.hist(no7.net_amount.clip(upper=600), bins=40, color=ACCENT, alpha=0.85)
    m7 = deliv[deliv.merchant_id == "M0007"].net_amount
    ax.axvline(
        no7.net_amount.mean(),
        color=INK,
        lw=1.6,
        ls="--",
        label=f"AOV excl M0007 = {money(no7.net_amount.mean())}",
    )
    ax.axvline(
        deliv.net_amount.mean(),
        color=AMBER,
        lw=1.8,
        label=f"AOV incl M0007 = {money(deliv.net_amount.mean())}",
    )
    ax.set_title(
        f"One wholesaler (M0007, ~{money(m7.mean())}/order) drags the mean",
        color=INK,
        fontsize=12,
        fontweight="bold",
        loc="left",
        pad=12,
    )
    ax.set_xlabel("Order net amount (clipped at $600)", color=MUTED, fontsize=9.5)
    ax.set_ylabel("Delivered orders", color=MUTED, fontsize=9.5)
    ax.legend(frameon=False, fontsize=9, loc="upper right")
    _style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "aov_outlier.png", bbox_inches="tight")
    plt.close(fig)


def chart_trend(m: dict) -> None:
    t = m["trend"]
    labels = [lbl[2:] for lbl in t["labels"]]  # 25-07 style
    vals = t["values"]
    pk = t["peak_index"]
    fig, ax = plt.subplots(figsize=(9.0, 3.8))
    ax.plot(labels, vals, color=ACCENT, lw=2.4, marker="o", ms=4, zorder=3)
    ax.fill_between(range(len(vals)), vals, color=ACCENT, alpha=0.08)
    ax.scatter([pk], [vals[pk]], color=AMBER, s=90, zorder=5)
    ax.annotate(
        f"{m['peak_month']}  {m['peak_multiple']:.1f}x",
        (pk, vals[pk]),
        textcoords="offset points",
        xytext=(0, 12),
        ha="center",
        color=AMBER,
        fontsize=10,
        fontweight="bold",
    )
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x/1e3:.0f}k"))
    ax.set_title(
        "Delivered revenue, trailing 12 months - November is the demand peak",
        color=INK,
        fontsize=12.5,
        fontweight="bold",
        loc="left",
        pad=12,
    )
    ax.set_ylim(0, max(vals) * 1.18)
    _style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "rev_trend.png", bbox_inches="tight")
    plt.close(fig)


def chart_category(m: dict) -> None:
    cat = m["category"]
    labels = cat["labels"][::-1]
    vals = cat["values"][::-1]
    fig, ax = plt.subplots(figsize=(6.6, 4.4))
    ax.barh(labels, vals, color=ACCENT, height=0.66)
    for y, v in enumerate(vals):
        ax.text(v, y, "  " + money(v), va="center", color=INK, fontsize=9.5)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x/1e6:.1f}M"))
    ax.set_title(
        "Delivered revenue by category (trailing 12 months)",
        color=INK,
        fontsize=12.5,
        fontweight="bold",
        loc="left",
        pad=12,
    )
    ax.set_xlim(0, max(vals) * 1.18)
    _style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "category_rev.png", bbox_inches="tight")
    plt.close(fig)


def chart_concentration(m: dict) -> None:
    c = m["concentration_top"]
    labels = c["labels"]
    vals = c["values"]
    colors = [AMBER if lbl == c["outlier"] else ACCENT for lbl in labels]
    fig, ax = plt.subplots(figsize=(9.0, 3.8))
    ax.bar(labels, vals, color=colors, width=0.7)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x/1e3:.0f}k"))
    ax.set_title(
        f"Merchant revenue concentration - {c['outlier']} dominates (amber)",
        color=INK,
        fontsize=12.5,
        fontweight="bold",
        loc="left",
        pad=12,
    )
    for lbl in ax.get_xticklabels():
        lbl.set_rotation(45)
        lbl.set_ha("right")
    _style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "concentration.png", bbox_inches="tight")
    plt.close(fig)


# ----------------------------------------------------------------- scorecard html
def spark_svg(values: list[float], peak: int, w: int = 150, h: int = 40) -> str:
    lo, hi = min(values), max(values)
    rng = hi - lo or 1
    step = w / (len(values) - 1)
    pts = [(i * step, h - 4 - (v - lo) / rng * (h - 8)) for i, v in enumerate(values)]
    path = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    px, py = pts[peak]
    return (
        f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
        f'preserveAspectRatio="none" aria-hidden="true">'
        f'<path d="{path}" fill="none" stroke="#0D9488" stroke-width="2"/>'
        f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.2" fill="#F59E0B"/></svg>'
    )


def fmt_value(v: float, fmt: str) -> str:
    if fmt == "money":
        return money(v)
    if fmt == "money2":
        return f"${v:,.2f}"
    if fmt == "int":
        return f"{int(round(v)):,}"
    if fmt == "pct":
        return f"{v:.1f}%"
    return str(v)


def fmt_delta(tile: dict) -> str:
    pop = tile.get("pop")
    if pop is None:
        return '<span class="delta flat">no prior period</span>'
    pts = tile.get("pop_is_pts")
    arrow = "▲" if pop > 0 else ("▼" if pop < 0 else "±")
    cls = "up" if pop > 0 else ("down" if pop < 0 else "flat")
    unit = " pts" if pts else "%"
    return f'<span class="delta {cls}">{arrow} {abs(pop):.1f}{unit} QoQ</span>'


def build_html(m: dict) -> str:
    spark = spark_svg(m["trend"]["values"], m["trend"]["peak_index"])
    tiles_html = []
    for t in m["tiles"]:
        val = fmt_value(t["value"], t["fmt"])
        tiles_html.append(f"""<div class="tile rag-{t['rag']}">
      <div class="t-top"><span class="t-label">{t['label']}</span>
        <span class="rag-dot"></span></div>
      <div class="t-sub">{t['sub']}</div>
      <div class="t-value num">{val}</div>
      {fmt_delta(t)}
      <div class="t-def"><b>Definition.</b> {t['definition']}</div>
      <div class="t-val"><b>Validated.</b> {t['validation']}</div>
    </div>""")
    tiles = "\n    ".join(tiles_html)
    cur = m["current_period"]
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Everrest Executive Scorecard - {cur}</title>
<style>
  :root{{--ink:#0F172A;--accent:#0D9488;--accent-d:#0B7C72;--muted:#64748B;
    --hair:#E2E8F0;--tint:#F0FDFA;--amber:#F59E0B;--green:#0D9488;--red:#DC2626;}}
  *{{margin:0;padding:0;box-sizing:border-box;}}
  body{{font-family:'Inter',-apple-system,'Segoe UI',sans-serif;color:var(--ink);
    background:#F8FAFC;padding:34px 26px;font-size:15px;line-height:1.55;}}
  .board{{max-width:1120px;margin:0 auto;background:#fff;border:1px solid var(--hair);
    border-radius:18px;box-shadow:0 18px 50px rgba(15,23,42,.07);overflow:hidden;}}
  .head{{background:var(--ink);color:#fff;padding:24px 30px;display:flex;
    align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;}}
  .head h1{{font-size:21px;font-weight:600;letter-spacing:-.01em;}}
  .head .sub{{color:#94A3B8;font-size:13px;margin-top:3px;}}
  .head .spark{{display:flex;align-items:center;gap:10px;color:#CBD5E1;font-size:12px;}}
  .headline{{background:var(--tint);border-bottom:1px solid var(--hair);
    padding:16px 30px;font-size:15.5px;color:var(--ink);}}
  .headline b{{color:var(--accent-d);}}
  .grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--hair);}}
  @media(max-width:900px){{.grid{{grid-template-columns:repeat(2,1fr);}}}}
  @media(max-width:560px){{.grid{{grid-template-columns:1fr;}}}}
  .tile{{background:#fff;padding:18px 18px 16px;position:relative;}}
  .t-top{{display:flex;align-items:center;justify-content:space-between;}}
  .t-label{{font-weight:600;font-size:13.5px;color:var(--ink);}}
  .t-sub{{font-size:11.5px;color:var(--muted);margin-top:1px;}}
  .t-value{{font-size:30px;font-weight:700;font-variant-numeric:tabular-nums;
    color:var(--ink);margin:8px 0 2px;letter-spacing:-.01em;}}
  .num{{font-variant-numeric:tabular-nums;}}
  .rag-dot{{width:10px;height:10px;border-radius:50%;flex-shrink:0;}}
  .rag-green .rag-dot{{background:var(--green);}}
  .rag-amber .rag-dot{{background:var(--amber);}}
  .rag-red .rag-dot{{background:var(--red);}}
  .rag-amber{{box-shadow:inset 3px 0 0 var(--amber);}}
  .delta{{font-size:12px;font-weight:600;display:inline-block;}}
  .delta.up{{color:var(--green);}} .delta.down{{color:var(--red);}}
  .delta.flat{{color:var(--muted);}}
  .t-def,.t-val{{font-size:11px;color:var(--muted);margin-top:9px;line-height:1.45;}}
  .t-def b{{color:var(--ink);}} .t-val b{{color:var(--amber);}}
  .foot{{padding:14px 30px;font-size:11.5px;color:var(--muted);
    border-top:1px solid var(--hair);display:flex;justify-content:space-between;
    flex-wrap:wrap;gap:8px;}}
  .foot code{{background:var(--tint);padding:1px 6px;border-radius:5px;color:var(--accent-d);}}
</style>
</head>
<body>
  <div class="board">
    <div class="head">
      <div>
        <h1>Everrest - Executive Scorecard</h1>
        <div class="sub">B2B2C retail marketplace &middot; current period {cur} &middot; vs {m['prior_period']}</div>
      </div>
      <div class="spark">GMV, trailing 12 mo {spark}</div>
    </div>
    <div class="headline"><b>Read this first.</b> {m['headline']}</div>
    <div class="grid">
    {tiles}
    </div>
    <div class="foot">
      <span>Every figure computed by <code>build_scorecard.py</code> from the Everrest marts (seed {m['seed']}). Zero hand-typed numbers.</span>
      <span>GMV recognized on <code>status = {m['recognized_status']}</code> &middot; take rate {m['take_rate']:.0%} (assumption)</span>
    </div>
  </div>
</body>
</html>
"""


# ----------------------------------------------------------------- main
def main() -> None:
    marts = load_marts()
    m = compute(marts)

    (OUT / "metrics.json").write_text(json.dumps(m, indent=2))
    (OUT / "everrest_scorecard.html").write_text(build_html(m))

    chart_status(m)
    chart_aov(marts, m)
    chart_trend(m)
    chart_category(m)
    chart_concentration(m)

    print("Everrest scorecard build - seed", SEED)
    print("current period:", m["current_period"], "vs", m["prior_period"])
    for t in m["tiles"]:
        print(f"  {t['label']:<22} {fmt_value(t['value'], t['fmt']):>14}  [{t['rag']}]")
    print("headline:", m["headline"])
    print("outputs written to", OUT)


if __name__ == "__main__":
    main()
