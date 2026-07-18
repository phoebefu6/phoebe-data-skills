"""Everrest RFM sample data generator.

Dedicated generator for the how-to-RFM skill. Same Everrest platform + schema
as the main case canon, seed 42, but customers are drawn from lifecycle
ARCHETYPES so an RFM segmentation has real structure to recover. (The frozen
generate_everrest.py stays untouched so how-to-EDA's numbers don't drift.)

Reference date for Recency = 2026-07-01 (analysis "today").

PLANTED PATTERNS (Step 5 checks recall of exactly these five):
1. WHALE CONCENTRATION - a small 'champion' + 'loyal' core (~16% of customers)
   drives the majority of monetary value (classic 80/20, steeper here).
2. CAN'T-LOSE-THEM - a tiny high-monetary segment that has gone quiet
   (recency > 120 days) - the highest-value win-back opportunity, invisible
   in an average.
3. AFFILIATE ONE-AND-DONE - single low-value order, never returned, heavily
   over-indexed on the 'affiliate' acquisition channel (ties to the EDA
   affiliate-tracker story).
4. NOV SIGNUP COHORT - customers acquired in the November promo spike who
   mostly never reactivated (seasonal acquisition that looks like growth but
   isn't retention).
5. RETURNS-HEAVY SEGMENT - a group with high order frequency whose net
   monetary is dragged low/negative by returns (frequency lies without value).

Run:  python generate_everrest_rfm.py   ->  writes ./data/*.csv
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
OUT = Path(__file__).parent / "data"
REF_DATE = pd.Timestamp("2026-07-01")  # "today" for recency
WINDOW_START = pd.Timestamp("2025-07-01")

N_CUSTOMERS = 20_000
CHANNELS = ["organic", "paid_search", "social", "email", "referral", "affiliate"]
REGIONS = ["SG", "MY", "ID", "TH", "VN", "PH"]

# Lifecycle archetypes: share of base + behaviour ranges.
# freq = lifetime order count; rec = days since last order; aov = avg order value ($).
ARCHETYPES = {
    #                     share  freq(lo,hi) recency(lo,hi)  aov(lo,hi)
    "champion": (0.05, (12, 30), (1, 30), (90, 260)),
    "loyal": (0.11, (6, 15), (10, 70), (55, 150)),
    "potential_loyalist": (0.14, (3, 6), (10, 60), (45, 110)),
    "new_customer": (0.10, (1, 2), (1, 40), (40, 120)),
    "promising": (0.08, (2, 4), (40, 90), (35, 90)),
    "need_attention": (0.09, (3, 6), (90, 150), (50, 120)),
    "at_risk": (0.10, (4, 9), (150, 260), (60, 160)),
    "cant_lose_them": (0.03, (8, 20), (150, 330), (120, 320)),  # whale lapsers
    "hibernating": (0.14, (2, 4), (200, 330), (30, 80)),
    "lost": (0.16, (1, 2), (280, 360), (20, 70)),
}


def make_customers(rng: np.random.Generator) -> pd.DataFrame:
    names = list(ARCHETYPES)
    shares = np.array([ARCHETYPES[a][0] for a in names])
    shares = shares / shares.sum()
    seg = rng.choice(names, N_CUSTOMERS, p=shares)

    df = pd.DataFrame(
        {
            "customer_id": [f"C{i:06d}" for i in range(1, N_CUSTOMERS + 1)],
            "_archetype": seg,
            "region": rng.choice(
                REGIONS, N_CUSTOMERS, p=[0.30, 0.20, 0.20, 0.12, 0.10, 0.08]
            ),
        }
    )

    # Channel: mostly balanced, but 'lost' + 'hibernating' skew to affiliate (pattern 3).
    ch_default = [0.26, 0.20, 0.17, 0.12, 0.10, 0.15]
    ch_affil = [0.10, 0.08, 0.07, 0.05, 0.05, 0.65]
    channel = np.empty(N_CUSTOMERS, dtype=object)
    is_oneanddone = np.isin(seg, ["lost", "hibernating"])
    channel[is_oneanddone] = rng.choice(CHANNELS, is_oneanddone.sum(), p=ch_affil)
    channel[~is_oneanddone] = rng.choice(CHANNELS, (~is_oneanddone).sum(), p=ch_default)
    df["channel_id"] = channel
    return df


def build_behaviour(rng: np.random.Generator, customers: pd.DataFrame) -> pd.DataFrame:
    """Turn each customer's archetype into concrete freq / recency / signup."""
    freq = np.empty(len(customers), dtype=int)
    recency = np.empty(len(customers), dtype=int)
    aov = np.empty(len(customers), dtype=float)
    for a, (_, (flo, fhi), (rlo, rhi), (alo, ahi)) in ARCHETYPES.items():
        m = customers._archetype.values == a
        n = int(m.sum())
        freq[m] = rng.integers(flo, fhi + 1, n)
        recency[m] = rng.integers(rlo, rhi + 1, n)
        aov[m] = rng.uniform(alo, ahi, n)

    df = customers.copy()
    df["_freq"] = freq
    df["_recency_days"] = recency
    df["_aov"] = aov.round(2)
    # last order date = REF_DATE - recency; signup before first order.
    df["_last_order"] = REF_DATE - pd.to_timedelta(recency, unit="D")

    # Pattern 4: a chunk of 'new'/'promising'/'lost' were acquired in Nov 2025 promo.
    nov_pool = df._archetype.isin(
        ["new_customer", "promising", "lost", "hibernating"]
    ).values
    nov_pick = nov_pool & (rng.random(len(df)) < 0.22)
    signup = REF_DATE - pd.to_timedelta(rng.integers(30, 360, len(df)), unit="D")
    nov_days = pd.Timestamp("2025-11-15") - WINDOW_START
    signup = pd.Series(signup)
    signup[nov_pick] = pd.Timestamp("2025-11-15") + pd.to_timedelta(
        rng.integers(0, 20, nov_pick.sum()), unit="D"
    )
    df["signup_date"] = pd.to_datetime(np.minimum(signup.values, df._last_order.values))
    df["_nov_cohort"] = nov_pick
    return df


def make_orders(rng: np.random.Generator, cust: pd.DataFrame) -> pd.DataFrame:
    """Explode each customer into `freq` orders between signup and last order."""
    rows = []
    cid = cust.customer_id.values
    signup = cust.signup_date.values.astype("datetime64[D]")
    last = cust._last_order.values.astype("datetime64[D]")
    freq = cust._freq.values
    aov = cust._aov.values
    ret_heavy = cust._archetype.values == "need_attention"  # pattern 5 carrier

    order_no = 1
    for i in range(len(cust)):
        n = int(freq[i])
        span = max((last[i] - signup[i]).astype(int), 1)
        # order offsets in days from signup; last order forced to `last`.
        offs = np.sort(rng.integers(0, span + 1, n))
        offs[-1] = span
        for k in range(n):
            ts = signup[i] + np.timedelta64(int(offs[k]), "D")
            rows.append(
                (f"OR{order_no:07d}", cid[i], pd.Timestamp(ts), aov[i], ret_heavy[i])
            )
            order_no += 1

    df = pd.DataFrame(
        rows, columns=["order_id", "customer_id", "order_ts", "_aov", "_ret_heavy"]
    )
    # jitter each order's value around the customer AOV.
    df["order_value"] = np.round(df._aov * rng.uniform(0.55, 1.6, len(df)), 2)
    # status: mostly delivered; need_attention returns a lot (pattern 5).
    p_ret = np.where(df._ret_heavy, 0.42, 0.06)
    df["status"] = np.where(rng.random(len(df)) < p_ret, "returned", "delivered")
    return df


def make_order_items(rng: np.random.Generator, orders: pd.DataFrame) -> pd.DataFrame:
    """Split each order value into 1-4 line items (keeps schema parallel to EDA)."""
    n_items = rng.choice([1, 2, 3, 4], len(orders), p=[0.5, 0.28, 0.15, 0.07])
    rep = orders.loc[orders.index.repeat(n_items)].copy()
    rep["_k"] = rep.groupby("order_id").cumcount()
    counts = rep.groupby("order_id").order_id.transform("size")
    # even-ish split of order_value across its items.
    rep["net"] = (rep.order_value / counts).round(2)
    rep["qty"] = rng.choice([1, 1, 2, 3], len(rep))
    rep["unit_price"] = (rep.net / rep.qty).round(2)
    rep["discount"] = np.round(rng.choice([0, 0, 0.05, 0.1, 0.2], len(rep)), 2)
    rep["product_id"] = [f"P{n:05d}" for n in rng.integers(1, 5000, len(rep))]
    return rep[
        ["order_id", "product_id", "qty", "unit_price", "discount", "net"]
    ].reset_index(drop=True)


def main() -> None:
    rng = np.random.default_rng(SEED)
    OUT.mkdir(exist_ok=True)

    customers = make_customers(rng)
    customers = build_behaviour(rng, customers)
    orders = make_orders(rng, customers)
    order_items = make_order_items(rng, orders)

    # Public tables mirror the Everrest schema (drop internal _cols).
    cust_out = customers[["customer_id", "signup_date", "channel_id", "region"]]
    orders_out = orders[["order_id", "customer_id", "order_ts", "status"]]
    items_out = order_items[["order_id", "product_id", "qty", "unit_price", "discount"]]

    # Ground-truth archetype labels kept for verification (not used by the analysis).
    truth = customers[["customer_id", "_archetype", "_nov_cohort"]].rename(
        columns={"_archetype": "archetype", "_nov_cohort": "nov_cohort"}
    )

    tables = {
        "customers": cust_out,
        "orders": orders_out,
        "order_items": items_out,
        "_ground_truth": truth,
    }
    total = 0
    for name, df in tables.items():
        df.to_csv(OUT / f"{name}.csv", index=False)
        total += len(df)
        print(f"{name:14s} {len(df):>8,d} rows")
    print(f"{'TOTAL':14s} {total:>8,d} rows  (seed={SEED}, ref_date={REF_DATE.date()})")


if __name__ == "__main__":
    main()
