"""Everrest demand forecast - Data Science flagship (charts track).

DECISION: how many units, and how many dollars, does each category need staged
for November 2026 - and do we repeat the March buy? Everrest runs a consignment
fulfilment programme, so the platform commits inventory in advance on the
merchants' behalf. Committing low costs lost margin; committing high costs
holding plus markdown.

THE TRAP THAT DECIDES THE PAGE. Read naively, the marts show TWO whole-month
demand spikes: November 2025 and March 2026. Only one of them is demand. The
March "spike" is 600 orders double-fired by a retry bug - exact duplicate
order_id rows whose join against order_items fans out roughly 4x. The
data-quality gate catches it, deduplicates, and the March spike evaporates
(1.49x becomes ~1.0x). v1 of this analysis skipped the gate, measured the
phantom, costed both arms of a buy for it, and recommended holding open a
six-figure option on a data defect. The gate runs FIRST now.

THE HARD PART, after cleaning. One real spike (November) observed exactly ONCE.
Weekly seasonality has about 48 observations per weekday and can be validated
properly; annual seasonality has one observation per month and cannot be
validated at all. This script refuses to hide that: it measures what is
measurable, names what is not as an explicit parameter, and turns the
un-measurable part into a costed decision instead of a fake confidence interval.

WHAT IS PROVEN HERE (measured, reproducible)
  - the duplicate-order defect: 600 duplicated order_id rows, all in 2026-03,
    with doubled item line-sets - and the exact units it adds to March
  - day-of-week seasonality, about 48 observations per weekday
  - 28-day accuracy of 5 candidate models, rolling origin, 8 folds
  - 120-day accuracy of ALL 5 candidates on a spike-imputed series
  - how forecast error grows with lead time inside the 28-day window
  - the November lift against a baseline that never saw it
  - within-month day-to-day variation of the November multiplier (bootstrap)

WHAT IS NOT PROVEN (named as a parameter, never faked)
  - that November repeats, and at what multiplier: n = 1 year. YOY_SIGMA below
    is the assumed year-to-year variation of the multiplier. It is an input. The
    sensitivity chart shows exactly how much the decision depends on it.
  - accuracy at the 153-day planning horizon: validation stops at 120 days

STATED ASSUMPTIONS (business inputs, not data facts)
  - MARGIN_RATE / OVERSTOCK_RATE drive the newsvendor service level. There is no
    COGS field in the marts, so these are inputs. CATEGORY_COST_OVERRIDES lets a
    planner set them per category; empty means the uniform assumption applies.
    COST_SCENARIOS sweeps them, because they move the buy harder than sigma.
  - inventory is committed in units of delivered demand, gross of returns

Marts were generated with seed 42 (see how-to-schema-and-warehouse). Every
random draw here uses numpy default_rng seeded from 42, so the whole run is
deterministic.

Run (from this folder):
    python forecast_demand.py
Outputs -> ./output/ :
    forecast.json                  every computed value
    forecast_commitments.csv       the per-category commitment table (units + $)
    november_weekly_staging.csv    units on hand by week, from the observed shape
    findings.md                    the written buy paper
    daily_series.png               the year as read vs cleaned, both months flagged
    phantom_march.png              the March spike before and after the DQ gate
    dow_profile.png                day-of-week seasonality, n per weekday
    evidence_count.png             observations per seasonal cycle (the thesis)
    leak_monthly.png               the monthly-dummy trap: 12 points, 12 params
    backtest_design.png            rolling-origin folds
    model_mape.png                 28-day accuracy, winner highlighted
    fold_mape.png                  per-fold error, spike folds flagged
    lead_time_error.png            error growth across the 28-day horizon
    long_horizon.png               120-day accuracy, all 5 models - new winner
    spike_lno.png                  November against a baseline that never saw it
    uplift_bootstrap.png           within-month variation of the multiplier
    mc_distribution.png            simulated November 2026 units, P50 / q* / P90
    yoy_sensitivity.png            how the commit moves with the assumed sigma
    cost_sensitivity.png           how the commit moves with the cost rates
    commit_by_category.png         the commitment per category
    cost_curve.png                 expected cost vs service level, optimum marked
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from statsmodels.tsa.holtwinters import ExponentialSmoothing  # noqa: E402

# ----------------------------------------------------------------- config
SEED = 42
RNG = np.random.default_rng(SEED)
HERE = Path(__file__).resolve().parent
MARTS = HERE.parent / "how-to-eda" / "data"
OUT = HERE / "output"

RECOGNIZED_STATUS = "delivered"  # demand that actually consumed stock
HORIZON = 28  # short-horizon backtest: days ahead per fold
MIN_TRAIN = 182  # first fold trains on 6 months
FOLD_STEP = 21  # origin advances 3 weeks per fold
LONG_HORIZON = 120  # long-horizon backtest, near the real planning distance
LONG_STEP = 31
PLAN_FROM = pd.Timestamp("2026-07-01")  # first day beyond the data
PLAN_MONTH = ("2026-11-01", "2026-11-30")  # the buy being planned

# the one REAL spike month: a whole-month lift, observed exactly once. (March
# 2026 looks like a second spike when the marts are read naively - the DQ gate
# in load_daily shows it is a duplicate-row defect, not demand.)
SPIKES = {"november": pd.Period("2025-11")}
PHANTOM_MONTH = pd.Period("2026-03")  # where the retry bug lives

# business assumptions for the newsvendor service level (NOT data facts)
MARGIN_RATE = 0.20  # lost margin per unit of unmet demand, share of unit price
OVERSTOCK_RATE = 0.08  # holding + markdown per leftover unit, share of price
CATEGORY_COST_OVERRIDES: dict[str, tuple[float, float]] = {}  # cat -> (margin, over)
COST_RATE = 1.0 - MARGIN_RATE  # unit cost as a share of price - what cash goes out

# the buy is signed in dollars, so the same sweep the sigma gets is run over the
# two cost rates. Peak-season leftovers do not resell at full price, so the high
# overstock rows are the realistic ones and they move the buy more than sigma.
COST_SCENARIOS: list[tuple[str, float, float]] = [
    ("25% margin / 25% overstock", 0.25, 0.25),
    ("35% margin / 20% overstock", 0.35, 0.20),
    ("20% margin / 8% overstock (filed)", MARGIN_RATE, OVERSTOCK_RATE),
    ("40% margin / 10% overstock", 0.40, 0.10),
    ("45% margin / 5% overstock", 0.45, 0.05),
]

# THE named unknown: year-to-year variation of a spike multiplier. Unmeasurable
# at n = 1 year, so it is an input with a sensitivity curve, not a finding.
YOY_SIGMA = 0.25
N_SIM = 10_000  # Monte Carlo draws, shared across every scenario

# Data Science layer - cyan. Amber is the shared anomaly / flag colour.
INK = "#0F172A"
CYAN = "#0891B2"
CYAN_D = "#075E75"
AMBER = "#F59E0B"
MUTED = "#64748B"
HAIR = "#E2E8F0"
RED = "#DC2626"

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


def _style(ax) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    for lbl in ax.get_xticklabels() + ax.get_yticklabels():
        lbl.set_color(MUTED)
        lbl.set_fontsize(9)


def _title(ax, text: str, size: float = 12.5) -> None:
    ax.set_title(text, color=INK, fontsize=size, fontweight="bold", loc="left", pad=12)


def units(x: float) -> str:
    return f"{x:,.0f}"


def mape(actual: np.ndarray, pred: np.ndarray) -> float:
    """Zero-demand days are masked, not divided by - an inf here would silently
    decide the model race by sort order on someone else's sparser data."""
    ok = actual > 0
    return float(np.mean(np.abs(actual[ok] - pred[ok]) / actual[ok]) * 100)


def depeak(s: pd.Series) -> pd.Series:
    """Drop the spike month(s). Leaves calendar gaps on purpose."""
    return s[~s.index.to_period("M").isin(list(SPIKES.values()))]


def impute_spikes(train: pd.Series) -> pd.Series:
    """Replace the spike months with the de-peaked trend, keeping the calendar whole.

    Deleting 30 and 31 days shifts every later weekday by 2 and 3 positions, which
    is why v1 excluded the weekly models from the long-horizon race and claimed
    they "cannot be fitted". They can - statsmodels never sees the index - but
    splicing across the gaps corrupts their weekly phase. Imputing instead keeps
    the phase intact so every model competes on measured error.

    Fitted on THIS training window only, so nothing later leaks backwards.
    """
    clean = depeak(train)
    mask = train.index.to_period("M").isin(list(SPIKES.values()))
    if not mask.any() or len(clean) < 60:
        return train
    beta, t0 = fit_loglin(clean)
    out = train.astype(float).copy()
    out.loc[mask] = predict_loglin(beta, t0, train.index[mask])
    return out


# ----------------------------------------------------------------- load
def validate_marts() -> None:
    """Fail loudly and usefully BEFORE any analysis runs on someone else's marts."""
    if not MARTS.exists():
        raise SystemExit(
            f"marts not found at {MARTS} - run generate_everrest.py in "
            f"{MARTS.parent} first, or point MARTS at your own tables"
        )
    needed = {
        "orders.csv": {"order_id", "order_ts", "status", "merchant_id"},
        "order_items.csv": {"order_id", "qty", "unit_price"},
        "merchants.csv": {"merchant_id", "category"},
        "returns.csv": {"order_id"},
    }
    for fname, cols in needed.items():
        path = MARTS / fname
        if not path.exists():
            raise SystemExit(f"missing mart: {path}")
        have = set(pd.read_csv(path, nrows=0).columns)
        if not cols <= have:
            raise SystemExit(
                f"{fname} is missing columns {sorted(cols - have)} - "
                f"found {sorted(have)}. Rename or adapt load_daily()."
            )


def dq_gate(
    orders: pd.DataFrame, items: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Deduplicate before anything is measured, and record what was removed.

    THE GATE THAT DECIDES THIS ANALYSIS. orders.csv carries 600 duplicated
    order_id rows - a retry bug, every one of them in 2026-03 - and the item
    generator also ran on the duplicated frame, so those orders carry a doubled
    set of item lines. An inner join then fans out roughly 4x on those ids.
    Read naively, that manufactures a second whole-month "demand spike" that v1
    of this analysis measured (1.49x), costed, and nearly bought stock for.

    Treatment: one order_id is one order. Duplicate order rows are dropped, and
    for each affected order the doubled line-set is halved (the retry re-fired
    the entire order, so the first half is the genuine order). Everything is
    counted and returned - the memo reports the defect, not just the fix.
    """
    dup_mask = orders.order_id.duplicated()
    n_dup = int(dup_mask.sum())
    dup_ids = set(orders.loc[dup_mask, "order_id"])
    months = (
        sorted(orders.loc[dup_mask, "order_ts"].dt.to_period("M").astype(str).unique())
        if n_dup
        else []
    )
    clean_orders = orders[~dup_mask].copy()

    dropped_lines = 0
    if dup_ids:
        affected = items.order_id.isin(dup_ids)
        keep_first_half = (
            items[affected].groupby("order_id").cumcount()
            < items[affected].groupby("order_id").order_id.transform("size") // 2
        )
        dropped_lines = int((~keep_first_half).sum())
        items = pd.concat([items[~affected], items[affected][keep_first_half]])

    report = {
        "duplicate_order_rows": n_dup,
        "affected_order_ids": len(dup_ids),
        "duplicate_months": months,
        "dropped_item_lines": dropped_lines,
    }
    if n_dup:
        print(
            f"DQ GATE: {n_dup} duplicate order_id rows (months: {', '.join(months)}) "
            f"- deduplicated, {dropped_lines} doubled item lines dropped"
        )
    return clean_orders, items, report


def _daily_series(
    orders: pd.DataFrame, items: pd.DataFrame, merchants: pd.DataFrame
) -> tuple[pd.Series, pd.DataFrame]:
    deliv = orders[orders.status == RECOGNIZED_STATUS]
    lines = deliv.merge(items, on="order_id", how="inner").merge(
        merchants[["merchant_id", "category"]], on="merchant_id", how="left"
    )
    lines["date"] = lines.order_ts.dt.floor("D")
    idx = pd.date_range(lines.date.min(), lines.date.max(), freq="D")
    total = lines.groupby("date").qty.sum().reindex(idx, fill_value=0).astype(float)
    total.index.name = "date"
    by_cat = (
        lines.pivot_table(index="date", columns="category", values="qty", aggfunc="sum")
        .reindex(idx)
        .fillna(0.0)
    )
    by_cat.index.name = "date"
    return total, by_cat


def load_daily() -> tuple[pd.Series, pd.DataFrame, dict, pd.Series]:
    """Daily delivered units, total and by category - AFTER the DQ gate.

    Also returns the as-read (pre-gate) daily series, so the phantom March
    spike can be shown before and after rather than silently repaired.

    Units, not dollars, for the demand model: the decision is how much stock to
    stage. That choice matters - the top wholesaler that dominates GMV is a
    rounding error in units, so the outlier treatment a revenue metric needs is
    the wrong move here. Dollars come back in at the commitment step, where the
    buy is signed.
    """
    orders = pd.read_csv(MARTS / "orders.csv", parse_dates=["order_ts"])
    items = pd.read_csv(MARTS / "order_items.csv")
    merchants = pd.read_csv(MARTS / "merchants.csv")
    returns = pd.read_csv(MARTS / "returns.csv")

    if not (orders.status == RECOGNIZED_STATUS).any():
        raise SystemExit(
            f"no orders with status '{RECOGNIZED_STATUS}' - found "
            f"{sorted(orders.status.unique())}. Set RECOGNIZED_STATUS."
        )

    raw_total, _ = _daily_series(orders, items, merchants)
    orders, items, dq = dq_gate(orders, items)
    total, by_cat = _daily_series(orders, items, merchants)

    if len(total) < MIN_TRAIN + HORIZON:
        raise SystemExit(
            f"need >= {MIN_TRAIN + HORIZON} days of data, got {len(total)}; "
            f"lower MIN_TRAIN ({MIN_TRAIN}) at your own risk"
        )
    missing_spikes = [
        k for k, p in SPIKES.items() if p not in set(total.index.to_period("M"))
    ]
    if missing_spikes:
        raise SystemExit(
            f"spike month(s) {missing_spikes} not in the data window "
            f"({total.index[0].date()} to {total.index[-1].date()}). SPIKES, "
            "PHANTOM_MONTH, PLAN_FROM and PLAN_MONTH are calendar constants for "
            "the Everrest window - set them for your data."
        )

    deliv = orders[orders.status == RECOGNIZED_STATUS]
    lines = deliv.merge(items, on="order_id", how="inner").merge(
        merchants[["merchant_id", "category"]], on="merchant_id", how="left"
    )
    unit_by_merchant = lines.groupby("merchant_id").qty.sum()
    top_merchant = str(unit_by_merchant.idxmax())
    returned_units = lines[lines.order_id.isin(set(returns.order_id))].qty.sum()
    context = {
        "days": int(len(total)),
        "first_day": str(total.index[0].date()),
        "last_day": str(total.index[-1].date()),
        "total_units": float(total.sum()),
        "depeaked_days": int(len(depeak(total))),
        "dq": dq,
        "top_merchant": top_merchant,
        "top_merchant_unit_share_pct": float(
            unit_by_merchant.max() / lines.qty.sum() * 100
        ),
        "returned_unit_share_pct": float(returned_units / lines.qty.sum() * 100),
        "categories": sorted(by_cat.columns),
        "median_price_by_cat": {
            str(c): float(g.unit_price.median())
            for c, g in lines.groupby("category", observed=True)
        },
    }
    return total, by_cat, context, raw_total


# ----------------------------------------------------------------- models
@dataclass(frozen=True)
class Fold:
    origin: int
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    hits_spike: str | None


def make_folds(y: pd.Series) -> list[Fold]:
    folds: list[Fold] = []
    origin = MIN_TRAIN
    while origin + HORIZON <= len(y):
        test = y.index[origin : origin + HORIZON]
        months = set(test.to_period("M"))
        hit = next((n for n, p in SPIKES.items() if p in months), None)
        folds.append(Fold(origin, y.index[origin - 1], test[0], test[-1], hit))
        origin += FOLD_STEP
    return folds


def f_naive_last(train: pd.Series, h: int) -> np.ndarray:
    return np.repeat(train.iloc[-1], h)


def f_snaive7(train: pd.Series, h: int) -> np.ndarray:
    last = train.iloc[-7:].to_numpy()
    return np.array([last[i % 7] for i in range(h)])


def f_ma28(train: pd.Series, h: int) -> np.ndarray:
    return np.repeat(train.iloc[-28:].mean(), h)


def f_holt_winters(train: pd.Series, h: int) -> np.ndarray:
    fit = ExponentialSmoothing(
        train.to_numpy(),
        trend="add",
        seasonal="add",
        seasonal_periods=7,
        initialization_method="estimated",
    ).fit(optimized=True)
    return np.asarray(fit.forecast(h))


def _design(dates: pd.DatetimeIndex, t0: pd.Timestamp) -> np.ndarray:
    """Linear trend in days plus 6 day-of-week dummies (Monday is the base)."""
    t = (dates - t0).days.to_numpy(dtype=float)
    dow = dates.dayofweek.to_numpy()
    dummies = np.zeros((len(dates), 6))
    for k in range(1, 7):
        dummies[:, k - 1] = (dow == k).astype(float)
    return np.column_stack([np.ones(len(dates)), t, dummies])


def fit_loglin(train: pd.Series) -> tuple[np.ndarray, pd.Timestamp]:
    """Fit log(units) ~ trend + weekday. Tolerates calendar gaps by design."""
    t0 = train.index[0]
    x = _design(train.index, t0)
    beta, *_ = np.linalg.lstsq(x, np.log(train.to_numpy()), rcond=None)
    return beta, t0


def predict_loglin(
    beta: np.ndarray, t0: pd.Timestamp, dates: pd.DatetimeIndex
) -> np.ndarray:
    return np.exp(_design(dates, t0) @ beta)


def f_loglin_dow(train: pd.Series, h: int) -> np.ndarray:
    beta, t0 = fit_loglin(train)
    future = pd.date_range(train.index[-1] + pd.Timedelta(days=1), periods=h, freq="D")
    return predict_loglin(beta, t0, future)


MODELS = {
    "naive (last day)": f_naive_last,
    "seasonal naive (7d)": f_snaive7,
    "moving average (28d)": f_ma28,
    "Holt-Winters (weekly)": f_holt_winters,
    "log-linear + weekday": f_loglin_dow,
}


def backtest(y: pd.Series, folds: list[Fold]) -> dict:
    """Rolling origin, expanding window, 28-day horizon. No peeking."""
    rows: list[dict] = []
    lead_err: dict[str, list[np.ndarray]] = {m: [] for m in MODELS}
    for f in folds:
        train = y.iloc[: f.origin]
        actual = y.iloc[f.origin : f.origin + HORIZON].to_numpy()
        for name, fn in MODELS.items():
            pred = np.clip(fn(train, HORIZON), 1.0, None)
            rows.append(
                {
                    "model": name,
                    "fold_origin": str(f.test_start.date()),
                    "hits_spike": f.hits_spike,
                    "mape": mape(actual, pred),
                    "mae": float(np.mean(np.abs(actual - pred))),
                    "rmse": float(np.sqrt(np.mean((actual - pred) ** 2))),
                }
            )
            lead_err[name].append(np.abs(actual - pred) / actual * 100)
    df = pd.DataFrame(rows)
    clean = df[df.hits_spike.isna()]
    summary = (
        df.groupby("model")
        .agg(mape_all=("mape", "mean"), mae=("mae", "mean"), rmse=("rmse", "mean"))
        .join(clean.groupby("model").mape.mean().rename("mape_normal_months"))
        .join(
            df[df.hits_spike.notna()]
            .groupby("model")
            .mape.mean()
            .rename("mape_spike_months")
        )
        .sort_values("mape_normal_months")
    )
    winner = str(summary.index[0])
    return {
        "per_fold": df,
        "summary": summary,
        "winner": winner,
        "lead_curve": np.mean(np.vstack(lead_err[winner]), axis=0),
    }


# --------------------------------------------------- long-horizon selection
def b_loglin(train: pd.Series, dates: pd.DatetimeIndex) -> np.ndarray:
    """Log-linear + weekday evaluated on ARBITRARY dates, gaps and all.

    The only model here that can interpolate - predict a month that sits inside
    the training window. That is why it, and not the race winner, is the model
    used to estimate the spike multipliers in `leave_month_out`.
    """
    beta, t0 = fit_loglin(train)
    return predict_loglin(beta, t0, dates)


def project_month(fn, train: pd.Series, month_days: pd.DatetimeIndex) -> np.ndarray:
    """Run any h-step model forward from the end of train to a future month."""
    h = int((month_days[-1] - train.index[-1]).days)
    pred = np.clip(fn(train, h), 1.0, None)
    future = pd.date_range(train.index[-1] + pd.Timedelta(days=1), periods=h, freq="D")
    return pd.Series(pred, index=future).reindex(month_days).to_numpy()


def backtest_long(y: pd.Series) -> dict:
    """Validate every model at the distance the buy is actually made.

    Train is imputed, not gapped (see `impute_spikes`), so all five candidates
    compete - the weekly models keep their phase and lose or win on measured
    error rather than by exclusion. Test days are de-peaked, so this measures the
    baseline component alone; the spike multiplier is estimated separately and
    never mixed in here.

    Honest limit: with 365 days and a 120-day window the test windows overlap
    heavily, so the fold count overstates the independent evidence. Both numbers
    are reported.
    """
    clean = depeak(y)
    rows: list[dict] = []
    agg_rel: dict[str, list[float]] = {m: [] for m in MODELS}
    origin_i = MIN_TRAIN
    folds = 0
    covered: list[pd.DatetimeIndex] = []
    while origin_i + LONG_HORIZON <= len(y):
        cut = y.index[origin_i]
        window_end = cut + pd.Timedelta(days=LONG_HORIZON - 1)
        train_imp = impute_spikes(y[y.index < cut])
        test = clean[(clean.index >= cut) & (clean.index <= window_end)]
        if len(train_imp) >= 120 and len(test) >= 40:
            folds += 1
            covered.append(test.index)
            full = pd.date_range(cut, window_end, freq="D")
            pos = full.get_indexer(test.index)
            actual = test.to_numpy()
            for name, fn in MODELS.items():
                pred = np.clip(fn(train_imp, len(full)), 1.0, None)[pos]
                rows.append(
                    {
                        "model": name,
                        "fold_origin": str(cut.date()),
                        "test_days": len(test),
                        "mape": mape(actual, pred),
                        "agg_rel_pct": float(
                            (pred.sum() - actual.sum()) / actual.sum() * 100
                        ),
                    }
                )
                agg_rel[name].append(float((pred.sum() - actual.sum()) / actual.sum()))
        origin_i += LONG_STEP
    df = pd.DataFrame(rows)
    summary = df.groupby("model").agg(
        mape=("mape", "mean"),
        abs_agg_bias_pct=("agg_rel_pct", lambda s: s.abs().mean()),
    )
    summary = summary.sort_values("mape")
    winner = str(summary.index[0])
    union = len(set().union(*[set(ix) for ix in covered])) if covered else 0
    total_days = sum(len(ix) for ix in covered)
    return {
        "per_fold": df,
        "summary": summary,
        "winner": winner,
        "folds": folds,
        "distinct_test_days": union,
        "effective_folds": round(union / (total_days / folds), 2) if folds else 0.0,
        "agg_rel_errors": agg_rel[winner],
    }


# ----------------------------------------------------------------- spikes
def leave_month_out(y: pd.Series, month: pd.Period, model_fn) -> dict:
    """Fit the baseline with BOTH spike months held out, then predict one of them.

    Holding out both matters: if November stays in the training data while March
    is predicted, the fitted level is inflated by November and March's multiplier
    comes out too small. v1 of this script made exactly that mistake.

    `model_fn` is always the log-linear + weekday model, whatever wins the
    long-horizon race: the target month sits INSIDE the series, so the baseline
    has to be interpolated, and no h-step model can do that.
    """
    train = depeak(y)
    target_days = y.index[y.index.to_period("M") == month]
    baseline = model_fn(train, target_days)
    actual = y[y.index.to_period("M") == month].to_numpy()
    return {
        "month": str(month),
        "days": int(len(actual)),
        "actual_units": float(actual.sum()),
        "baseline_units": float(baseline.sum()),
        "uplift": float(actual.sum() / baseline.sum()),
        "extra_units": float(actual.sum() - baseline.sum()),
        "actual_arr": actual,
        "baseline_arr": baseline,
        "baseline_daily": baseline.tolist(),
        "actual_daily": actual.tolist(),
        "dates": [str(d.date()) for d in target_days],
        "mape_if_ignored": mape(actual, baseline),
        "held_out": [str(p) for p in SPIKES.values()],
    }


def bootstrap_uplift(
    actual: np.ndarray,
    baseline: np.ndarray,
    draws: int = 4000,
    rng: np.random.Generator | None = None,
) -> dict:
    """Resample the month's days to bound the multiplier.

    Days are resampled JOINTLY and the statistic is the ratio of sums, so the
    bootstrap centre equals the point estimate reported everywhere else. (v1
    bootstrapped a mean of daily ratios, which disagreed with the ratio of sums
    in the second decimal - two numbers for one quantity.)

    HONEST SCOPE: this covers day-to-day variation WITHIN the one month observed.
    It is deliberately narrow, and on its own it is NOT the uncertainty of the
    decision - the year-to-year term (YOY_SIGMA) dominates and is added later.
    """
    rng = rng or np.random.default_rng([SEED, 3])
    n = len(actual)
    idx = rng.integers(0, n, size=(draws, n))
    means = actual[idx].sum(axis=1) / baseline[idx].sum(axis=1)
    return {
        "point": float(actual.sum() / baseline.sum()),
        "p05": float(np.percentile(means, 5)),
        "p50": float(np.percentile(means, 50)),
        "p95": float(np.percentile(means, 95)),
        "spread_pct": float(
            (np.percentile(means, 95) - np.percentile(means, 5))
            / np.percentile(means, 50)
            * 100
        ),
        "draws": means,
        "scope": (
            "within-month day variation only; year-to-year variation is "
            "unobservable at n = 1 year and is added via YOY_SIGMA"
        ),
    }


# ----------------------------------------------------------------- the plan
def draw_components(n_resid: int, n_boot: int, n: int = N_SIM) -> dict:
    """Draw the random components ONCE so every scenario reuses them.

    Common random numbers. v1 re-drew inside every sensitivity step, so the
    sigma = 0.25 row of the sensitivity table disagreed with the headline commit
    computed from the same input - two answers for one number on a page whose
    thesis is reproducibility.
    """
    return {
        "resid_idx": RNG.integers(0, n_resid, size=n),
        "within_idx": RNG.integers(0, n_boot, size=n),
        "z": RNG.standard_normal(n),
    }


def simulate_november(
    baseline_total: float,
    up_draws: np.ndarray,
    long_resid: list[float],
    sigma: float,
    comp: dict,
) -> np.ndarray:
    """Three variance sources, two measured and one declared.

    measured : baseline error at a 120-day horizon (long-horizon backtest).
               `agg_rel_pct` is (pred - actual) / actual, so a draw of the truth
               is pred / (1 + e). v1 multiplied by (1 + e), which pushed the whole
               distribution the wrong way - the residuals are not symmetric, the
               model under-forecasts on average, so the sign mattered.
    measured : within-month day variation of the multiplier (bootstrap)
    declared : YOY_SIGMA, the year-to-year variation of the multiplier - n = 1
               year, so it cannot be measured. Median-preserving lognormal:
               exp(sigma * z) already has median 1. v1 also subtracted
               sigma^2 / 2, which makes the MEAN 1 and drags the median down, so
               the sensitivity chart appeared to show expected demand falling as
               uncertainty rose. That was an artifact, not a finding.
    """
    resid = np.asarray(long_resid, dtype=float)[comp["resid_idx"]]
    base = baseline_total / (1.0 + resid)
    within = np.asarray(up_draws)[comp["within_idx"]]
    return base * within * np.exp(comp["z"] * sigma)


def november_plan(
    y: pd.Series,
    by_cat: pd.DataFrame,
    boot: dict,
    long_bt: dict,
    context: dict,
) -> dict:
    """The buy, in units and in dollars, pooled and per category.

    Two things changed here after review. (1) Every category is now simulated on
    its OWN baseline and its OWN November multiplier, so its commit is a real
    newsvendor quantity. v1 took one platform quantile and split it by share,
    which gives every category the identical 15.1% buffer and quietly spends the
    pooling benefit without earning it. (2) The buy is priced. A commitment in
    units cannot be approved by anyone who owns the P&L.
    """
    clean = depeak(y)
    nov_days = pd.date_range(*PLAN_MONTH, freq="D")
    train_imp = impute_spikes(y)
    baselines = {
        name: float(project_month(fn, train_imp, nov_days).sum())
        for name, fn in MODELS.items()
    }
    baseline_total = baselines[long_bt["winner"]]
    beta, _ = fit_loglin(clean)

    # category split from the observed November - the only November there is
    nov_mask = by_cat.index.to_period("M") == SPIKES["november"]
    nov_shares = by_cat[nov_mask].sum() / by_cat[nov_mask].sum().sum()
    all_shares = by_cat.sum() / by_cat.sum().sum()
    share_drift_pts = float((nov_shares - all_shares).abs().max() * 100)

    resid = long_bt["agg_rel_errors"]
    comp = draw_components(len(resid), len(boot["draws"]))
    sim = simulate_november(baseline_total, boot["draws"], resid, YOY_SIGMA, comp)
    q_star = MARGIN_RATE / (MARGIN_RATE + OVERSTOCK_RATE)
    p50 = float(np.percentile(sim, 50))
    p_star = float(np.percentile(sim, q_star * 100))
    p90 = float(np.percentile(sim, 90))

    price_w = float(
        np.average(
            [context["median_price_by_cat"][c] for c in context["categories"]],
            weights=[nov_shares[c] for c in context["categories"]],
        )
    )

    # ---- per-category newsvendor: each category gets its own simulation
    rows = []
    for cat in context["categories"]:
        share = float(nov_shares[cat])
        price = context["median_price_by_cat"][cat]
        m_rate, o_rate = CATEGORY_COST_OVERRIDES.get(cat, (MARGIN_RATE, OVERSTOCK_RATE))
        cat_q = m_rate / (m_rate + o_rate)
        series_c = by_cat[cat]
        lno_c = leave_month_out(series_c, SPIKES["november"], b_loglin)
        boot_c = bootstrap_uplift(lno_c["actual_arr"], lno_c["baseline_arr"])
        base_c = float(
            project_month(
                MODELS[long_bt["winner"]], impute_spikes(series_c), nov_days
            ).sum()
        )
        # same year draw for every category (one year, one outcome), own day noise
        comp_c = dict(
            comp, within_idx=RNG.integers(0, len(boot_c["draws"]), size=N_SIM)
        )
        sim_c = simulate_november(base_c, boot_c["draws"], resid, YOY_SIGMA, comp_c)
        commit_c = float(np.percentile(sim_c, cat_q * 100))
        p50_c = float(np.percentile(sim_c, 50))
        rows.append(
            {
                "category": cat,
                "nov_share_pct": round(share * 100, 2),
                "baseline_units": round(base_c),
                "p50_units": round(p50_c),
                "commit_units": round(commit_c),
                "p90_units": round(float(np.percentile(sim_c, 90))),
                "buffer_over_p50_units": round(commit_c - p50_c),
                "service_level": round(cat_q, 3),
                "nov_uplift": round(boot_c["point"], 2),
                "median_unit_price": round(price, 2),
                "commit_cost_usd": round(commit_c * price * COST_RATE),
                "commit_retail_usd": round(commit_c * price),
                "stockout_cost_per_unit": round(price * m_rate, 2),
                "overstock_cost_per_unit": round(price * o_rate, 2),
            }
        )
    commitments = pd.DataFrame(rows)
    cat_commit_total = float(commitments.commit_units.sum())
    cat_p50_total = float(commitments.p50_units.sum())

    levels = np.arange(0.50, 0.9751, 0.005)
    costs = []
    for lv in levels:
        q = np.percentile(sim, lv * 100)
        short = np.maximum(sim - q, 0).mean() * price_w * MARGIN_RATE
        over = np.maximum(q - sim, 0).mean() * price_w * OVERSTOCK_RATE
        costs.append(short + over)
    costs_arr = np.asarray(costs)

    # sensitivity 1: the one declared parameter, sigma
    sens = []
    for s in (0.0, 0.10, 0.20, YOY_SIGMA, 0.35, 0.50):
        sim_s = simulate_november(baseline_total, boot["draws"], resid, s, comp)
        sens.append(
            {
                "sigma": s,
                "p50": float(np.percentile(sim_s, 50)),
                "commit": float(np.percentile(sim_s, q_star * 100)),
                "p90": float(np.percentile(sim_s, 90)),
            }
        )

    # sensitivity 2: the two cost rates, which are also assumptions and which
    # move the buy harder than sigma does
    cost_sens = []
    for label, m_rate, o_rate in COST_SCENARIOS:
        q = m_rate / (m_rate + o_rate)
        u = float(np.percentile(sim, q * 100))
        cost_sens.append(
            {
                "label": label,
                "margin": m_rate,
                "overstock": o_rate,
                "q_star": q,
                "commit_units": u,
                "commit_cost_usd": u * price_w * (1.0 - m_rate),
                "filed": abs(m_rate - MARGIN_RATE) < 1e-9
                and abs(o_rate - OVERSTOCK_RATE) < 1e-9,
            }
        )

    commit_cost = float(commitments.commit_cost_usd.sum())
    p50_cost = cat_p50_total * price_w * COST_RATE
    spike_bet_units = cat_commit_total - float(commitments.baseline_units.sum())
    return {
        "baseline_model": long_bt["winner"],
        "baseline_candidates": baselines,
        "baseline_total_units": baseline_total,
        "trend_pct_per_month": float((np.exp(beta[1] * 30) - 1) * 100),
        "horizon_days": int((pd.Timestamp(PLAN_MONTH[1]) - PLAN_FROM).days + 1),
        "validated_horizon_days": LONG_HORIZON,
        "yoy_sigma": YOY_SIGMA,
        "nov_shares": {k: float(v) for k, v in nov_shares.items()},
        "share_drift_pts": share_drift_pts,
        "q_star": q_star,
        "p50_units": p50,
        "commit_units": p_star,
        "p90_units": p90,
        "band_width_pct": float((p90 - p50) / p50 * 100),
        "cat_commit_total_units": cat_commit_total,
        "cat_p50_total_units": cat_p50_total,
        "pooling_gap_units": cat_commit_total - p_star,
        "commit_cost_usd": commit_cost,
        "commit_retail_usd": float(commitments.commit_retail_usd.sum()),
        "p50_cost_usd": p50_cost,
        "p90_cost_usd": float(commitments.p90_units.sum()) * price_w * COST_RATE,
        "option_tranche_cost_usd": commit_cost - p50_cost,
        "spike_bet_units": spike_bet_units,
        "spike_bet_cost_usd": spike_bet_units * price_w * COST_RATE,
        "spike_bet_share_pct": spike_bet_units / cat_commit_total * 100,
        "sim": sim,
        "levels": levels.tolist(),
        "costs": costs_arr.tolist(),
        "best_level_empirical": float(levels[int(costs_arr.argmin())]),
        "min_expected_cost_usd": float(costs_arr.min()),
        "price_weighted": price_w,
        "commitments": commitments,
        "uplift_used": boot["point"],
        "sensitivity": sens,
        "cost_sensitivity": cost_sens,
    }


def phantom_march(raw_total: pd.Series, total: pd.Series, plan: dict) -> dict:
    """The March buy question, answered by the DQ gate rather than a forecast.

    v1 skipped the gate, so it saw March 2026 at 1.49x baseline, could find no
    driver in the marts, costed both arms of a repeat buy and left a six-figure
    option open. The driver WAS in the marts: 600 duplicate order rows. Measured
    here on both series, same method (baseline fit with November and March held
    out, then March predicted):

      as read : the phantom multiplier v1 measured
      cleaned : March against the same baseline after dedup - no spike remains

    The costed lesson: the stock that a 1.49x repeat buy would have staged is
    priced at cost, because that is the cash a data defect nearly committed.
    """
    hold = list(SPIKES.values()) + [PHANTOM_MONTH]

    def _march_vs_baseline(series: pd.Series) -> dict:
        train = series[~series.index.to_period("M").isin(hold)]
        days = series.index[series.index.to_period("M") == PHANTOM_MONTH]
        baseline = b_loglin(train, days)
        actual = series[series.index.to_period("M") == PHANTOM_MONTH].to_numpy()
        return {
            "actual_units": float(actual.sum()),
            "baseline_units": float(baseline.sum()),
            "uplift": float(actual.sum() / baseline.sum()),
            "extra_units": float(actual.sum() - baseline.sum()),
            "actual_daily": actual.tolist(),
            "baseline_daily": baseline.tolist(),
        }

    raw = _march_vs_baseline(raw_total)
    clean = _march_vs_baseline(total)
    price_w = plan["price_weighted"]
    return {
        "month": str(PHANTOM_MONTH),
        "as_read": raw,
        "cleaned": clean,
        "defect_units": raw["actual_units"] - clean["actual_units"],
        "phantom_buy_units": raw["extra_units"],
        "phantom_buy_cost_usd": raw["extra_units"] * price_w * COST_RATE,
        "note": (
            "the multiplier v1 measured was a duplicate-row defect, not demand; "
            "the March recommendation is: fix the retry bug, stock nothing"
        ),
    }


# ----------------------------------------------------------------- charts
def chart_daily(y: pd.Series, raw: pd.Series) -> None:
    fig, ax = plt.subplots(figsize=(10.4, 3.9))
    ghost = raw.reindex(y.index)
    diff = ghost > y * 1.02
    ax.plot(
        y.index[diff],
        ghost[diff].to_numpy(),
        color=RED,
        lw=0.9,
        alpha=0.7,
        label="as read (duplicate rows)",
    )
    ax.plot(y.index, y.to_numpy(), color=CYAN, lw=0.9, alpha=0.85)
    ax.plot(
        y.index, y.rolling(7, center=True).mean(), color=INK, lw=2.0, label="7-day mean"
    )
    for _, per in SPIKES.items():
        m = y.index.to_period("M") == per
        ax.fill_between(y.index[m], 0, y[m].to_numpy(), color=AMBER, alpha=0.30)
        ax.annotate(
            f"{per.strftime('%B %Y')}\nreal spike",
            (y.index[m][len(y.index[m]) // 2], y[m].max()),
            textcoords="offset points",
            xytext=(0, 12),
            ha="center",
            color=AMBER,
            fontsize=10,
            fontweight="bold",
        )
    pm = y.index.to_period("M") == PHANTOM_MONTH
    if pm.any() and diff.any():
        ax.annotate(
            f"{PHANTOM_MONTH.strftime('%B %Y')}\nphantom - retry bug",
            (y.index[pm][len(y.index[pm]) // 2], float(ghost[pm].max())),
            textcoords="offset points",
            xytext=(0, 12),
            ha="center",
            color=RED,
            fontsize=10,
            fontweight="bold",
        )
    _title(ax, "One of the two spikes is demand - the other is duplicate rows")
    ax.set_ylabel("Delivered units / day", color=MUTED, fontsize=9.5)
    ax.set_ylim(0, max(y.max(), float(ghost.max())) * 1.24)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    _style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "daily_series.png", bbox_inches="tight")
    plt.close(fig)


def chart_phantom(ph: dict) -> None:
    """The March 'spike' before and after the DQ gate, same baseline."""
    fig, axes = plt.subplots(1, 2, figsize=(11.0, 3.9), sharey=True)
    for ax, key, bar_color, tag in (
        (axes[0], "as_read", RED, "as read - what v1 measured"),
        (axes[1], "cleaned", CYAN, "after the DQ gate"),
    ):
        d = ph[key]
        x = np.arange(len(d["actual_daily"]))
        ax.bar(x, d["actual_daily"], color=bar_color, width=0.72, alpha=0.8)
        ax.plot(
            x,
            d["baseline_daily"],
            color=INK,
            lw=2.0,
            label="baseline (never saw March)",
        )
        _title(ax, f"{tag}: {d['uplift']:.2f}x", size=12.0)
        ax.set_xlabel("day of March 2026", color=MUTED, fontsize=9)
    axes[0].set_ylabel("Delivered units", color=MUTED, fontsize=9)
    axes[0].legend(fontsize=8.5, loc="upper right", frameon=False)
    fig.suptitle(
        f"The 1.49x March spike was {ph['as_read']['actual_units'] - ph['cleaned']['actual_units']:,.0f} "
        f"units of duplicate rows - a repeat buy would have staged "
        f"${ph['phantom_buy_cost_usd']:,.0f} of stock for a retry bug",
        x=0.01,
        ha="left",
        color=INK,
        fontsize=12.5,
        fontweight="bold",
    )
    for ax in axes:
        _style(ax)
    fig.tight_layout(rect=(0, 0, 1, 0.90))
    fig.savefig(OUT / "phantom_march.png", bbox_inches="tight")
    plt.close(fig)


def chart_dow(y: pd.Series) -> dict:
    clean = depeak(y)
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    grp = clean.groupby(clean.index.dayofweek)
    means, counts = grp.mean(), grp.size()
    overall = clean.mean()
    fig, ax = plt.subplots(figsize=(6.6, 4.0))
    colors = [AMBER if v > overall else CYAN for v in means]
    bars = ax.bar(names, means.to_numpy(), color=colors, width=0.66)
    for b, v, n in zip(bars, means.to_numpy(), counts.to_numpy(), strict=True):
        ax.text(
            b.get_x() + b.get_width() / 2,
            v,
            f"{v:,.0f}\nn={n}",
            ha="center",
            va="bottom",
            color=INK,
            fontsize=8.5,
        )
    ax.axhline(overall, color=INK, ls="--", lw=1.2, label=f"mean {overall:,.0f}/day")
    _title(
        ax,
        f"Weekday seasonality IS validatable - {counts.min()} to {counts.max()} "
        "observations each",
    )
    ax.set_ylabel("Delivered units / day", color=MUTED, fontsize=9.5)
    ax.set_ylim(0, means.max() * 1.30)
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    _style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "dow_profile.png", bbox_inches="tight")
    plt.close(fig)
    return {
        "weekday_means": {n: float(v) for n, v in zip(names, means, strict=True)},
        "obs_per_weekday_min": int(counts.min()),
        "obs_per_weekday_max": int(counts.max()),
        "weekend_lift_pct": float(
            means.iloc[5:].mean() / means.iloc[:5].mean() * 100 - 100
        ),
    }


def chart_evidence(y: pd.Series, dow: dict) -> None:
    """Same de-peaked series as the weekday chart, so the counts agree."""
    cycles = ["Weekday\n(7 slots)", "Month of year\n(12 slots)"]
    obs = [float(dow["obs_per_weekday_min"]), 1.0]
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    bars = ax.bar(cycles, obs, color=[CYAN, AMBER], width=0.55)
    for b, v in zip(bars, obs, strict=True):
        ax.text(
            b.get_x() + b.get_width() / 2,
            v,
            f"  {v:,.0f} obs\n  per slot",
            ha="center",
            va="bottom",
            color=INK,
            fontsize=11,
            fontweight="bold",
        )
    ax.axhline(1, color=RED, ls="--", lw=1.3)
    ax.text(
        1.0,
        4.6,
        "1 observation:\nnothing left to validate against",
        color=RED,
        fontsize=9.5,
        ha="center",
        fontweight="bold",
    )
    _title(ax, "Why one of these seasonalities is knowledge and one is a guess")
    ax.set_ylabel("Observations per seasonal slot", color=MUTED, fontsize=9.5)
    ax.set_yscale("log")
    ax.set_ylim(0.62, 200)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:g}"))
    _style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "evidence_count.png", bbox_inches="tight")
    plt.close(fig)


def chart_leak(y: pd.Series) -> dict:
    """The trap: month dummies at monthly grain fit perfectly and prove nothing."""
    monthly = y.groupby(y.index.to_period("M")).sum()
    n = len(monthly)
    x = np.eye(n)  # n observations, n parameters -> exact fit, 0 residual df
    beta, *_ = np.linalg.lstsq(x, monthly.to_numpy(), rcond=None)
    fitted = x @ beta
    in_sample_mape = mape(monthly.to_numpy(), fitted)
    fig, ax = plt.subplots(figsize=(9.6, 3.9))
    labels = [str(p)[2:] for p in monthly.index]
    ax.bar(labels, monthly.to_numpy(), color=HAIR, width=0.62, label="actual units")
    ax.plot(
        labels, fitted, color=RED, lw=2.2, marker="o", ms=5, label="month-dummy fit"
    )
    ax.set_xlabel(
        f"in-sample MAPE {in_sample_mape:.1f}%   R-squared 1.000   "
        f"{n} observations, {n} parameters, 0 residual degrees of freedom",
        color=RED,
        fontsize=10.5,
        fontweight="bold",
        labelpad=10,
    )
    _title(ax, "A perfect fit that proves nothing - the model memorised the year")
    ax.set_ylabel("Delivered units / month", color=MUTED, fontsize=9.5)
    ax.set_ylim(0, monthly.max() * 1.16)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    _style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "leak_monthly.png", bbox_inches="tight")
    plt.close(fig)
    return {
        "n_obs": n,
        "n_params": n,
        "residual_df": 0,
        "in_sample_mape": in_sample_mape,
        "monthly_units": {str(k): float(v) for k, v in monthly.items()},
    }


def chart_folds(y: pd.Series, folds: list[Fold]) -> None:
    fig, ax = plt.subplots(figsize=(9.8, 4.0))
    for i, f in enumerate(folds):
        ax.barh(i, (f.train_end - y.index[0]).days, left=0, color=HAIR, height=0.6)
        ax.barh(
            i,
            HORIZON,
            left=(f.test_start - y.index[0]).days,
            color=AMBER if f.hits_spike else CYAN,
            height=0.6,
        )
    for per in SPIKES.values():
        days = y.index[y.index.to_period("M") == per]
        ax.axvspan(
            (days[0] - y.index[0]).days,
            (days[-1] - y.index[0]).days,
            color=AMBER,
            alpha=0.12,
        )
    ax.set_yticks(range(len(folds)))
    ax.set_yticklabels(
        [f"fold {i + 1}  {f.test_start.date()}" for i, f in enumerate(folds)]
    )
    _title(
        ax,
        f"Rolling origin: {len(folds)} folds, train grows, {HORIZON}-day test "
        "never seen",
    )
    ax.set_xlabel(
        "Day index (grey = train, coloured = test)", color=MUTED, fontsize=9.5
    )
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    _style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "backtest_design.png", bbox_inches="tight")
    plt.close(fig)


def chart_model_mape(summary: pd.DataFrame, winner: str, n_folds: int) -> None:
    s = summary.sort_values("mape_normal_months", ascending=False)
    has_spike = s.mape_spike_months.notna().any()
    fig, ax = plt.subplots(figsize=(8.6, 4.2))
    ypos = np.arange(len(s))
    ax.barh(
        ypos,
        s.mape_normal_months.to_numpy(),
        color=[CYAN if i == s.index[-1] else HAIR for i in s.index],
        height=0.52,
        label="normal months",
    )
    if has_spike:
        ax.scatter(
            s.mape_spike_months.to_numpy(),
            ypos,
            color=AMBER,
            s=64,
            zorder=5,
            label="folds containing a spike",
        )
    for i, (nm, sp) in enumerate(
        zip(s.mape_normal_months, s.mape_spike_months, strict=True)
    ):
        ax.text(nm, i, f"  {nm:.1f}%", va="center", color=INK, fontsize=10)
        if has_spike and not np.isnan(sp):
            ax.text(
                sp,
                i - 0.36,
                f"{sp:.0f}%",
                va="center",
                ha="center",
                color=AMBER,
                fontsize=9,
            )
    ax.set_yticks(ypos)
    ax.set_yticklabels(s.index)
    ax.set_title(
        f"28-day accuracy, {n_folds} rolling folds - winner: {winner}",
        color=INK,
        fontsize=12.5,
        fontweight="bold",
        loc="left",
        pad=32,
    )
    xlab = "MAPE (lower is better)"
    if not has_spike:
        xlab += (
            "\nno fold reaches the spike month (it sits before the first\n"
            "valid test origin) - the spike is validated by leave-month-out"
        )
    ax.set_xlabel(xlab, color=MUTED, fontsize=9)
    xmax = np.nanmax(
        [s.mape_normal_months.max(), s.mape_spike_months.max() if has_spike else 0]
    )
    ax.set_xlim(0, xmax * 1.18)
    ax.legend(
        frameon=False,
        fontsize=9,
        loc="lower right",
        bbox_to_anchor=(1.0, 1.0),
        ncol=2,
    )
    ax.grid(axis="y", visible=False)
    _style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "model_mape.png", bbox_inches="tight")
    plt.close(fig)


def chart_fold_mape(per_fold: pd.DataFrame, winner: str) -> None:
    w = per_fold[per_fold.model == winner]
    fig, ax = plt.subplots(figsize=(9.4, 3.9))
    colors = [AMBER if s else CYAN for s in w.hits_spike.notna()]
    bars = ax.bar(w.fold_origin.to_numpy(), w.mape.to_numpy(), color=colors, width=0.62)
    for b, v, s in zip(bars, w.mape.to_numpy(), w.hits_spike, strict=True):
        ax.text(
            b.get_x() + b.get_width() / 2,
            v,
            f"{v:.0f}%" + (f"\n{s}" if isinstance(s, str) else ""),
            ha="center",
            va="bottom",
            color=AMBER if isinstance(s, str) else INK,
            fontsize=9,
            fontweight="bold" if isinstance(s, str) else "normal",
        )
    spike_folds = w.hits_spike.notna().any()
    _title(
        ax,
        (
            f"{winner}: accurate on normal months, wrong by design on spikes"
            if spike_folds
            else f"{winner}: fold-by-fold error - every fold is a normal month"
        ),
    )
    ax.set_ylabel("Fold MAPE", color=MUTED, fontsize=9.5)
    ax.set_xlabel("Test window start", color=MUTED, fontsize=9.5)
    ax.set_ylim(0, w.mape.max() * 1.32)
    _style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "fold_mape.png", bbox_inches="tight")
    plt.close(fig)


def chart_lead(curve: np.ndarray, plan: dict, winner: str) -> None:
    fig, ax = plt.subplots(figsize=(8.6, 3.9))
    days = np.arange(1, len(curve) + 1)
    ax.plot(days, curve, color=CYAN, lw=2.2, marker="o", ms=3.5)
    slope = float(np.polyfit(days, curve, 1)[0])
    ax.annotate(
        f"error grows about {slope:.2f} pts per extra day of lead time",
        (days[-1], curve[-1]),
        textcoords="offset points",
        xytext=(-10, 14),
        ha="right",
        color=CYAN_D,
        fontsize=10,
        fontweight="bold",
    )
    ax.axvspan(1, len(curve), color=CYAN, alpha=0.06)
    ax.text(
        len(curve) * 0.5,
        curve.max() * 1.18,
        f"this model validated to {HORIZON} days  |  the November buy is "
        f"{plan['horizon_days']} days out",
        ha="center",
        color=RED,
        fontsize=10,
        fontweight="bold",
    )
    _title(ax, f"How far ahead {winner} was actually proven to work")
    ax.set_xlabel("Lead time (days ahead)", color=MUTED, fontsize=9.5)
    ax.set_ylabel("Mean absolute % error", color=MUTED, fontsize=9.5)
    ax.set_ylim(0, curve.max() * 1.34)
    _style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "lead_time_error.png", bbox_inches="tight")
    plt.close(fig)


def chart_long_horizon(long_bt: dict, short_winner: str) -> None:
    s = long_bt["summary"].sort_values("mape", ascending=False)
    fig, ax = plt.subplots(figsize=(8.6, 2.9))
    ypos = np.arange(len(s))
    ax.barh(
        ypos,
        s.mape.to_numpy(),
        color=[CYAN if i == s.index[-1] else HAIR for i in s.index],
        height=0.62,
    )
    for i, (m, b) in enumerate(zip(s.mape, s.abs_agg_bias_pct, strict=True)):
        ax.text(
            m,
            i,
            f"  {m:.1f}% MAPE   ·   {b:.1f}% total-volume bias",
            va="center",
            color=INK,
            fontsize=10,
        )
    ax.set_yticks(ypos)
    ax.set_yticklabels(s.index)
    _title(
        ax,
        f"At {LONG_HORIZON} days the {HORIZON}-day winner loses - "
        f"{long_bt['winner']} extrapolates best",
    )
    ax.set_xlabel(
        f"All 5 models, spike month imputed in train, de-peaked test. "
        f"{long_bt['folds']} folds whose windows overlap - about "
        f"{long_bt['effective_folds']:.0f} independent comparisons, not "
        f"{long_bt['folds']}",
        color=MUTED,
        fontsize=9,
    )
    ax.set_xlim(0, s.mape.max() * 1.62)
    ax.grid(axis="y", visible=False)
    _style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "long_horizon.png", bbox_inches="tight")
    plt.close(fig)


def chart_spike_lno(lno: dict[str, dict]) -> None:
    d = lno["november"]
    fig, ax = plt.subplots(figsize=(9.6, 3.9))
    x = np.arange(d["days"])
    ax.bar(x, d["actual_daily"], color=AMBER, width=0.72, label="actual")
    ax.plot(
        x, d["baseline_daily"], color=INK, lw=2.0, label="baseline, November held out"
    )
    _title(
        ax,
        f"November ran {d['uplift']:.2f}x a baseline that never saw it - "
        f"{units(d['extra_units'])} extra units",
    )
    ax.set_xlabel(
        f"day of month  ·  ignoring the spike leaves a forecast "
        f"{d['mape_if_ignored']:.0f}% low",
        color=MUTED,
        fontsize=9,
    )
    ax.set_ylabel("Delivered units", color=MUTED, fontsize=9)
    ax.legend(
        fontsize=8.5,
        loc="lower right",
        frameon=True,
        facecolor="white",
        edgecolor=HAIR,
        framealpha=0.94,
    )
    _style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "spike_lno.png", bbox_inches="tight")
    plt.close(fig)


def chart_uplift(boot: dict[str, dict]) -> None:
    b = boot["november"]
    fig, ax = plt.subplots(figsize=(8.6, 3.9))
    ax.hist(b["draws"], bins=48, color=AMBER, alpha=0.75, label="November multiplier")
    ax.axvline(b["point"], color=AMBER, lw=2.0)
    top = ax.get_ylim()[1]
    ax.annotate(
        f"{b['point']:.2f}x\n[{b['p05']:.2f}, {b['p95']:.2f}]",
        (b["point"], top * 0.84),
        textcoords="offset points",
        xytext=(8, 0),
        color=CYAN_D,
        fontsize=10,
        fontweight="bold",
    )
    _title(
        ax,
        f"The multiplier is tight within its month ({b['spread_pct']:.0f}% spread) "
        "- the real risk is year-to-year",
    )
    ax.set_xlabel(
        "Month units / baseline units, days resampled within the one November "
        "observed. Year-to-year variation is unobservable at n = 1 and enters as "
        "the declared sigma.",
        color=MUTED,
        fontsize=9.5,
    )
    ax.set_ylabel("Bootstrap draws", color=MUTED, fontsize=9.5)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    _style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "uplift_bootstrap.png", bbox_inches="tight")
    plt.close(fig)


def chart_mc(plan: dict) -> None:
    sim = plan["sim"]
    fig, ax = plt.subplots(figsize=(9.4, 4.0))
    ax.hist(sim, bins=60, color=CYAN, alpha=0.78)
    top = ax.get_ylim()[1]
    buy = plan["cat_commit_total_units"]
    marks = (
        (plan["p50_units"], "P50", INK, 0.94, -8),
        (buy, "the buy\n(sum of category commits)", AMBER, 0.62, 8),
        (plan["p90_units"], "P90", RED, 0.94, 8),
    )
    for val, lbl, color, dy, dx in marks:
        ax.axvline(val, color=color, lw=2.0, ls="--" if lbl == "P50" else "-")
        ax.annotate(
            f"{lbl}\n{units(val)}",
            (val, top * dy),
            textcoords="offset points",
            xytext=(dx, 0),
            ha="right" if dx < 0 else "left",
            color=color,
            fontsize=9.5,
            fontweight="bold",
        )
    ax.set_xlim(float(np.percentile(sim, 0.2)) * 0.92, float(np.percentile(sim, 99.6)))
    _title(
        ax,
        f"{units(buy)} units is the cheapest place to stand in a range this wide",
    )
    ax.set_xlabel(
        f"Simulated total units, {N_SIM:,} draws (seed {SEED}). P50 to P90 spans "
        f"{plan['band_width_pct']:.0f}%; baseline error rests on 3 folds - thin, "
        "and said so",
        color=MUTED,
        fontsize=9,
    )
    ax.set_ylabel("Draws", color=MUTED, fontsize=9.5)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v / 1e3:.0f}k"))
    _style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "mc_distribution.png", bbox_inches="tight")
    plt.close(fig)


def chart_sensitivity(plan: dict) -> None:
    s = plan["sensitivity"]
    sig = [d["sigma"] for d in s]
    fig, ax = plt.subplots(figsize=(8.6, 3.9))
    ax.plot(
        [x * 100 for x in sig],
        [d["p50"] for d in s],
        color=INK,
        lw=2.0,
        marker="o",
        label="P50",
    )
    ax.plot(
        [x * 100 for x in sig],
        [d["commit"] for d in s],
        color=AMBER,
        lw=2.6,
        marker="o",
        label=f"commit at q*={plan['q_star']:.2f}",
    )
    ax.plot(
        [x * 100 for x in sig],
        [d["p90"] for d in s],
        color=RED,
        lw=2.0,
        marker="o",
        ls="--",
        label="P90",
    )
    ax.axvline(plan["yoy_sigma"] * 100, color=CYAN, lw=1.4, ls=":")
    ax.annotate(
        f"assumed {plan['yoy_sigma']:.0%}",
        (plan["yoy_sigma"] * 100, ax.get_ylim()[1] * 0.95),
        textcoords="offset points",
        xytext=(6, -10),
        color=CYAN_D,
        fontsize=9.5,
        fontweight="bold",
    )
    _title(ax, "The one number that is assumed, and what it does to the buy")
    ax.set_xlabel(
        "Assumed year-to-year variation of the November multiplier (sigma, %)",
        color=MUTED,
        fontsize=9.5,
    )
    ax.set_ylabel("November 2026 units", color=MUTED, fontsize=9.5)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v / 1e3:.0f}k"))
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    _style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "yoy_sensitivity.png", bbox_inches="tight")
    plt.close(fig)


def chart_commit(plan: dict) -> None:
    c = plan["commitments"].sort_values("commit_units")
    fig, ax = plt.subplots(figsize=(8.8, 4.4))
    y = np.arange(len(c))
    ax.hlines(y, c.p50_units, c.p90_units, color=HAIR, lw=6)
    ax.scatter(c.p50_units, y, color=INK, s=44, zorder=4, label="P50 (expected)")
    ax.scatter(
        c.commit_units, y, color=AMBER, s=92, zorder=5, label="commit (cost-optimal)"
    )
    ax.scatter(c.p90_units, y, color=RED, s=44, zorder=4, label="P90 (cautious)")
    for i, r in enumerate(c.itertuples()):
        ax.text(
            r.p90_units,
            i,
            f"  {units(r.commit_units)}",
            va="center",
            color=INK,
            fontsize=9.5,
        )
    ax.set_yticks(y)
    ax.set_yticklabels(c.category)
    _title(ax, "November 2026 commitment by category - units to stage")
    ax.set_xlabel("Delivered units", color=MUTED, fontsize=9.5)
    ax.set_xlim(0, c.p90_units.max() * 1.22)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    ax.grid(axis="y", visible=False)
    _style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "commit_by_category.png", bbox_inches="tight")
    plt.close(fig)


def chart_cost(plan: dict) -> None:
    levels = np.asarray(plan["levels"]) * 100
    costs = np.asarray(plan["costs"])
    fig, ax = plt.subplots(figsize=(8.6, 3.9))
    ax.plot(levels, costs, color=CYAN, lw=2.4)
    i = int(np.argmin(costs))
    ax.scatter([levels[i]], [costs[i]], color=AMBER, s=110, zorder=5)
    ax.annotate(
        f"q* = {plan['q_star']:.2f} (empirical argmin {levels[i] / 100:.3f})\n"
        f"${costs[i]:,.0f} expected cost of error",
        (levels[i], costs[i]),
        textcoords="offset points",
        xytext=(14, 26),
        color=AMBER,
        fontsize=10,
        fontweight="bold",
    )
    ax.axvline(plan["q_star"] * 100, color=INK, ls="--", lw=1.3)
    ax.annotate(
        f"newsvendor q* = {plan['q_star']:.2f}",
        (plan["q_star"] * 100, costs.max() * 0.9),
        textcoords="offset points",
        xytext=(-8, 0),
        ha="right",
        color=INK,
        fontsize=9.5,
    )
    _title(ax, "Being short costs more than being long, so plan above the middle")
    ax.set_xlabel(
        "Service level (percentile of the simulated demand)", color=MUTED, fontsize=9.5
    )
    ax.set_ylabel("Expected cost of error", color=MUTED, fontsize=9.5)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v / 1e3:.0f}k"))
    _style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "cost_curve.png", bbox_inches="tight")
    plt.close(fig)


def chart_cost_sensitivity(plan: dict) -> None:
    """The un-tested assumption that moves the buy hardest: the two cost rates."""
    cs = sorted(plan["cost_sensitivity"], key=lambda d: d["q_star"])
    fig, ax = plt.subplots(figsize=(9.4, 4.2))
    ypos = np.arange(len(cs))
    colors = [AMBER if d["filed"] else CYAN for d in cs]
    ax.barh(ypos, [d["commit_units"] for d in cs], color=colors, height=0.58)
    for i, d in enumerate(cs):
        ax.text(
            d["commit_units"],
            i,
            f"  {units(d['commit_units'])} u   ·   "
            f"${d['commit_cost_usd'] / 1e3:,.0f}k at cost   ·   q*={d['q_star']:.2f}",
            va="center",
            color=INK,
            fontsize=9.5,
            fontweight="bold" if d["filed"] else "normal",
        )
    ax.set_yticks(ypos)
    ax.set_yticklabels([d["label"] for d in cs])
    lo = min(d["commit_cost_usd"] for d in cs)
    hi = max(d["commit_cost_usd"] for d in cs)
    _title(
        ax,
        f"The cost rates finance must confirm swing the buy by "
        f"${(hi - lo) / 1e3:,.0f}k of committed cash",
    )
    ax.set_xlabel(
        "November commitment (units). Amber = the rates filed in this memo - "
        "inputs, not findings; no COGS field exists in the marts",
        color=MUTED,
        fontsize=9,
    )
    ax.set_xlim(0, max(d["commit_units"] for d in cs) * 1.72)
    ax.grid(axis="y", visible=False)
    _style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "cost_sensitivity.png", bbox_inches="tight")
    plt.close(fig)


# ----------------------------------------------------------------- staging
def write_weekly_staging(plan: dict, lno_nov: dict) -> pd.DataFrame:
    """Units on hand by week of November, from the observed daily shape.

    A buy meeting needs 'units on hand by week', not one month-total. The one
    November observed already carries the within-month shape; the commit is
    spread along it.
    """
    daily = np.asarray(lno_nov["actual_daily"], dtype=float)
    share = daily / daily.sum()
    dates = pd.to_datetime(lno_nov["dates"]) + pd.DateOffset(years=1)
    df = pd.DataFrame(
        {
            "date": dates,
            "week": [f"W{((d.day - 1) // 7) + 1}" for d in dates],
            "demand_share_pct": share * 100,
        }
    )
    weekly = df.groupby("week", as_index=False).demand_share_pct.sum()
    weekly["commit_units"] = (
        weekly.demand_share_pct / 100 * plan["cat_commit_total_units"]
    ).round()
    weekly["cumulative_units"] = weekly.commit_units.cumsum()
    weekly["demand_share_pct"] = weekly.demand_share_pct.round(1)
    weekly.to_csv(OUT / "november_weekly_staging.csv", index=False)
    return weekly


# ----------------------------------------------------------------- memo
def write_findings(res: dict) -> None:
    plan, lno, ctx, ph = res["plan"], res["lno"], res["context"], res["phantom"]
    bt, long_bt, dow = res["bt"], res["long_bt"], res["dow"]
    c = plan["commitments"]
    sens = plan["sensitivity"]
    commit_lo = min(s["commit"] for s in sens)
    commit_hi = max(s["commit"] for s in sens)
    p90_lo = min(s["p90"] for s in sens)
    p90_hi = max(s["p90"] for s in sens)
    cost_lo = min(s["commit_cost_usd"] for s in plan["cost_sensitivity"])
    cost_hi = max(s["commit_cost_usd"] for s in plan["cost_sensitivity"])
    firm_units = plan["cat_p50_total_units"]
    option_units = plan["cat_commit_total_units"] - firm_units
    lines = [
        "# Everrest November 2026 buy paper",
        "",
        f"Seed {SEED}. Every number below is computed by `forecast_demand.py` from "
        f"the Everrest marts ({ctx['first_day']} to {ctx['last_day']}, "
        f"{ctx['days']} days, {ctx['total_units']:,.0f} delivered units after the "
        "data-quality gate).",
        "",
        "## The decision",
        "",
        f"Stage **{units(plan['cat_commit_total_units'])} units** for November "
        f"2026: **${plan['commit_retail_usd']:,.0f} at retail, "
        f"${plan['commit_cost_usd']:,.0f} committed at cost** (unit cost taken as "
        f"{COST_RATE:.0%} of price - the complement of the stated margin). Of that "
        f"cash, ${plan['spike_bet_cost_usd']:,.0f} "
        f"({plan['spike_bet_share_pct']:.0f}% of the buy) rides on the November "
        f"peak repeating at {plan['uplift_used']:.2f}x, an event observed once. "
        f"P50 is {units(plan['cat_p50_total_units'])} units "
        f"(${plan['p50_cost_usd']:,.0f} at cost) and P90 is "
        f"{units(float(c.p90_units.sum()))} (${plan['p90_cost_usd']:,.0f}): a "
        f"{plan['band_width_pct']:.0f}% band between the middle and the cautious "
        "case, because a five-month-ahead forecast of a once-observed peak "
        "deserves a wide band and gets one here. Being wrong on the service "
        f"level costs about ${plan['min_expected_cost_usd']:,.0f} either way at "
        "the optimum.",
        "",
        "**How to commit it.** Place the P50 tranche "
        f"(**{units(firm_units)} units, ${plan['p50_cost_usd']:,.0f} at cost**) "
        f"as the firm buy now. Hold the remaining {units(option_units)} units "
        f"(${plan['option_tranche_cost_usd']:,.0f}) as a late-cut or "
        "reserved-capacity option, released on the September and October "
        f"run-rate against the {plan['trend_pct_per_month']:+.1f}%/month baseline "
        f"trend. The forecast is validated to {LONG_HORIZON} days and November is "
        f"{plan['horizon_days']} days out - the option tranche is what buys the "
        "right to be wrong in that unvalidated tail for "
        f"${plan['option_tranche_cost_usd']:,.0f} instead of the full "
        f"${plan['commit_cost_usd']:,.0f}. Weekly staging profile in "
        "`november_weekly_staging.csv`.",
        "",
        "## The March buy is cancelled - the spike was never demand",
        "",
        f"Read naively, March 2026 runs at {ph['as_read']['uplift']:.2f}x its "
        f"baseline - {units(ph['phantom_buy_units'])} apparent extra units, and a "
        f"repeat buy would stage ${ph['phantom_buy_cost_usd']:,.0f} of stock at "
        "cost. The data-quality gate found the driver no forecast could: "
        f"**{ctx['dq']['duplicate_order_rows']} duplicate order_id rows** - a "
        "retry bug, every one of them in March - whose join against order_items "
        "fans out about 4x. Deduplicated, March sits at "
        f"{ph['cleaned']['uplift']:.2f}x baseline: an ordinary month. The v1 "
        "draft of this analysis skipped the gate, measured the phantom at "
        f"{ph['as_read']['uplift']:.2f}x, could not name a driver, and left a "
        "six-figure option open on it. The recommendation is an engineering "
        "ticket, not a purchase order: fix the retry bug, add a duplicate-key "
        "check to ingestion, stock nothing.",
        "",
        "## What was measured",
        "",
        f"- The defect: {ctx['dq']['duplicate_order_rows']} duplicate order rows "
        f"across {ctx['dq']['affected_order_ids']} orders, "
        f"{ctx['dq']['dropped_item_lines']} doubled item lines dropped, all in "
        f"{', '.join(ctx['dq']['duplicate_months'])}.",
        f"- Weekday seasonality: {dow['obs_per_weekday_min']} to "
        f"{dow['obs_per_weekday_max']} observations per weekday on de-peaked "
        f"days; weekend runs {dow['weekend_lift_pct']:.0f}% above weekdays.",
        f"- Short-horizon model selection: {len(MODELS)} candidates, rolling "
        f"origin, {bt['n_folds']} folds, {HORIZON}-day horizon. Winner "
        f"**{bt['winner']}** at "
        f"{bt['summary'].mape_normal_months.iloc[0]:.1f}% MAPE. Honest gap: no "
        "fold reaches the spike month - it sits before the first valid test "
        "origin - so the spike is validated by leave-month-out, not by the "
        "backtest.",
        f"- Long-horizon selection: all {len(MODELS)} candidates at "
        f"{LONG_HORIZON} days, spike month imputed in train, de-peaked test. "
        f"Winner **{long_bt['winner']}** at "
        f"{long_bt['summary'].mape.iloc[0]:.1f}% MAPE. Honest caveat: the "
        f"{long_bt['folds']} fold windows overlap - about "
        f"{long_bt['effective_folds']:.0f} independent comparisons.",
        f"- Underlying trend on de-peaked days: "
        f"{plan['trend_pct_per_month']:+.1f}% per month.",
        f"- The November lift against a baseline that never saw it: "
        f"{lno['november']['uplift']:.2f}x, "
        f"{units(lno['november']['extra_units'])} extra units.",
        "",
        "## What was not measured, and is not pretended",
        "",
        "- That November repeats at all: n = 1 year. The bootstrap band covers "
        "day-to-day variation inside the one November observed - a "
        f"{res['boot']['november']['spread_pct']:.0f}% spread, which is why it "
        "is not used alone.",
        f"- Year-to-year variation of the multiplier is an INPUT: sigma = "
        f"{YOY_SIGMA:.0%}. Nothing in 12 months of data can estimate it - and "
        "the commit barely cares: across sigma 0% to 50% the buy moves "
        f"{units(commit_lo)} to {units(commit_hi)} units, about "
        f"{(commit_hi - commit_lo) / commit_lo * 100:.0f}%. The P90 is not "
        f"robust - it runs {units(p90_lo)} to {units(p90_hi)} over the same "
        "range. The buy is safe against this assumption; the worst case is not.",
        f"- Accuracy at the planning horizon: validation reaches {LONG_HORIZON} "
        f"days, the November buy is {plan['horizon_days']} days out.",
        f"- The baseline uncertainty rests on {len(long_bt['agg_rel_errors'])} "
        "fold residuals - thin, and said so on the chart.",
        f"- Category split comes from the single November observed; the largest "
        f"category share moves {plan['share_drift_pts']:.1f} points if taken "
        "from all 12 months instead.",
        f"- Per-category commits are simulated per category (own baseline, own "
        "multiplier, shared year draw) and sum to "
        f"{units(plan['cat_commit_total_units'])} - "
        f"{units(abs(plan['pooling_gap_units']))} units above the pooled "
        "platform quantile. That gap is the price of promising each category "
        "its own service level instead of spending the pooling benefit "
        "without earning it.",
        "",
        "## Commitment table",
        "",
        "| Category | Nov share | P50 | Commit | Commit $ (cost) | P90 | Buffer over P50 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in c.sort_values("commit_units", ascending=False).itertuples():
        lines.append(
            f"| {r.category} | {r.nov_share_pct:.1f}% | {units(r.p50_units)} | "
            f"**{units(r.commit_units)}** | ${r.commit_cost_usd:,.0f} | "
            f"{units(r.p90_units)} | {units(r.buffer_over_p50_units)} |"
        )
    lines += [
        "",
        f"Totals: **{units(plan['cat_commit_total_units'])} units, "
        f"${plan['commit_cost_usd']:,.0f} at cost**. The service level is "
        f"{plan['q_star']:.2f} in every row because the cost rates are assumed "
        "uniform - `CATEGORY_COST_OVERRIDES` in the script is where a planner "
        "sets real per-category economics (a perishable category belongs at a "
        "much lower q*).",
        "",
        "## The two numbers finance must confirm before this is approved",
        "",
        f"Margin rate {MARGIN_RATE:.0%} and overstock rate {OVERSTOCK_RATE:.0%} "
        f"of unit price set q* = {plan['q_star']:.2f} and therefore the entire "
        "buy. There is no COGS field in the marts, so they are inputs, not "
        "findings - and they move the commitment by "
        f"${cost_hi - cost_lo:,.0f} of committed cash across plausible rates, "
        "the same order of magnitude as the sigma assumption (about "
        f"${(commit_hi - commit_lo) * plan['price_weighted'] * COST_RATE:,.0f}). "
        "Neither is measurable from the marts; both are declared inputs with a "
        "sensitivity chart. "
        "On rates typical of peak-season stock (35% margin, 20% overstock) the "
        "commit falls to "
        f"{units(next(s['commit_units'] for s in plan['cost_sensitivity'] if s['margin'] == 0.35))} "
        "units. See `cost_sensitivity.png`.",
        "",
        "## Other assumptions a reader may want to change",
        "",
        f"- Year-to-year sigma {YOY_SIGMA:.0%} on the spike multiplier "
        "(median-preserving lognormal).",
        "- Demand is committed gross of returns. "
        f"{ctx['returned_unit_share_pct']:.1f}% of units sit on orders that "
        "later had a return - an order-level upper bound (the returns mart has "
        "no line detail), and returned units re-enter supply mid-month, so the "
        "commit is not padded for them.",
        f"- Units, not revenue, for the demand model: the top merchant by units "
        f"({ctx['top_merchant']}) is {ctx['top_merchant_unit_share_pct']:.2f}% "
        "of units, so the outlier handling a revenue metric needs does not "
        "apply here. Dollars enter at the commitment step.",
        "",
        "## The data request that would end the guessing",
        "",
        "One more November. Until then: log a promotion and campaign calendar "
        "as first-class fields, add a duplicate-key check to ingestion so the "
        "next retry bug is caught at load time, and record supplier lead time, "
        "MOQ and pack size per category so the commitment table can become a "
        "purchase order.",
        "",
    ]
    (OUT / "findings.md").write_text("\n".join(lines))


# ----------------------------------------------------------------- main
def main() -> None:
    OUT.mkdir(exist_ok=True)
    validate_marts()
    total, by_cat, context, raw_total = load_daily()
    folds = make_folds(total)
    if not folds:
        raise SystemExit(
            f"no backtest folds fit: {len(total)} days, MIN_TRAIN={MIN_TRAIN}, "
            f"HORIZON={HORIZON}"
        )

    chart_daily(total, raw_total)
    dow = chart_dow(total)
    chart_evidence(total, dow)
    leak = chart_leak(total)
    chart_folds(total, folds)

    bt = backtest(total, folds)
    bt["n_folds"] = len(folds)
    chart_model_mape(bt["summary"], bt["winner"], len(folds))
    chart_fold_mape(bt["per_fold"], bt["winner"])

    long_bt = backtest_long(total)
    if long_bt["folds"] < 4:
        print(
            f"NOTE: only {long_bt['folds']} long-horizon folds "
            f"(~{long_bt['effective_folds']:.0f} independent) - the baseline "
            "winner rests on thin evidence, and the memo says so"
        )
    chart_long_horizon(long_bt, bt["winner"])

    # b_loglin, not the race winner: the spike month sits INSIDE the series and
    # must be interpolated, which no h-step model can do.
    lno = {k: leave_month_out(total, p, b_loglin) for k, p in SPIKES.items()}
    boot = {
        k: bootstrap_uplift(
            v["actual_arr"],
            v["baseline_arr"],
            rng=np.random.default_rng([SEED, 3, i]),
        )
        for i, (k, v) in enumerate(lno.items())
    }
    chart_spike_lno(lno)
    chart_uplift(boot)

    plan = november_plan(total, by_cat, boot["november"], long_bt, context)
    phantom = phantom_march(raw_total, total, plan)
    chart_phantom(phantom)
    chart_lead(bt["lead_curve"], plan, bt["winner"])
    chart_mc(plan)
    chart_sensitivity(plan)
    chart_cost_sensitivity(plan)
    chart_commit(plan)
    chart_cost(plan)

    plan["commitments"].to_csv(OUT / "forecast_commitments.csv", index=False)
    weekly = write_weekly_staging(plan, lno["november"])
    res = {
        "context": context,
        "dow": dow,
        "leak": leak,
        "bt": bt,
        "long_bt": long_bt,
        "lno": lno,
        "boot": boot,
        "plan": plan,
        "phantom": phantom,
    }
    write_findings(res)

    dumpable = {
        "seed": SEED,
        "context": context,
        "weekday": dow,
        "monthly_dummy_trap": leak,
        "backtest_short": {
            "horizon_days": HORIZON,
            "folds": len(folds),
            "winner": bt["winner"],
            "summary": bt["summary"].round(2).to_dict(orient="index"),
            "per_fold": bt["per_fold"].round(2).to_dict(orient="records"),
            "lead_curve_pct": [round(v, 2) for v in bt["lead_curve"]],
        },
        "backtest_long": {
            "horizon_days": LONG_HORIZON,
            "folds": long_bt["folds"],
            "effective_folds": long_bt["effective_folds"],
            "winner": long_bt["winner"],
            "summary": long_bt["summary"].round(2).to_dict(orient="index"),
            "per_fold": long_bt["per_fold"].round(2).to_dict(orient="records"),
            "agg_rel_errors": [round(v, 4) for v in long_bt["agg_rel_errors"]],
        },
        "spikes": {
            k: {
                kk: vv
                for kk, vv in v.items()
                if kk not in ("actual_arr", "baseline_arr")
            }
            for k, v in lno.items()
        },
        "uplift_bootstrap": {
            k: {kk: vv for kk, vv in v.items() if kk != "draws"}
            for k, v in boot.items()
        },
        "plan": {
            k: v
            for k, v in plan.items()
            if k not in ("sim", "commitments", "levels", "costs")
        },
        "phantom_march": phantom,
        "commitments": plan["commitments"].to_dict(orient="records"),
        "weekly_staging": weekly.to_dict(orient="records"),
    }
    (OUT / "forecast.json").write_text(json.dumps(dumpable, indent=2, default=str))

    print(f"\nEverrest demand forecast - seed {SEED}")
    print(
        f"data: {context['first_day']} to {context['last_day']} ({context['days']} days)"
    )
    print(f"\n28-day rolling origin, {len(folds)} folds:")
    print(bt["summary"].round(2).to_string())
    print(f"  short-horizon winner: {bt['winner']}")
    print(
        f"\n{LONG_HORIZON}-day, imputed train / de-peaked test, "
        f"{long_bt['folds']} folds (~{long_bt['effective_folds']:.0f} independent):"
    )
    print(long_bt["summary"].round(2).to_string())
    print(f"  long-horizon winner (used for the baseline): {long_bt['winner']}")
    v = lno["november"]
    print(
        f"\nNovember spike (held out of the baseline fit): {v['uplift']:.2f}x, "
        f"+{units(v['extra_units'])} units"
    )
    print(
        f"phantom March: {phantom['as_read']['uplift']:.2f}x as read -> "
        f"{phantom['cleaned']['uplift']:.2f}x after dedup "
        f"(${phantom['phantom_buy_cost_usd']:,.0f} of stock NOT bought)"
    )
    print(
        f"\nNovember 2026 baseline {units(plan['baseline_total_units'])} units "
        f"({plan['baseline_model']}), multiplier {plan['uplift_used']:.2f}x, "
        f"year sigma {YOY_SIGMA:.0%}"
    )
    print(
        f"  P50 {units(plan['cat_p50_total_units'])}  commit(q*={plan['q_star']:.2f}) "
        f"{units(plan['cat_commit_total_units'])} units = "
        f"${plan['commit_cost_usd']:,.0f} at cost  P90 "
        f"{units(float(plan['commitments'].p90_units.sum()))}  "
        f"(band {plan['band_width_pct']:.0f}%)"
    )
    print(f"  horizon: validated {LONG_HORIZON}d, planning {plan['horizon_days']}d")
    print(f"\noutputs written to {OUT}")


if __name__ == "__main__":
    main()
