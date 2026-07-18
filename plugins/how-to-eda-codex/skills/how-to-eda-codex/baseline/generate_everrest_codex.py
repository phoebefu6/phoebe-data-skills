"""Everrest sample data generator - Codex EDA edition.

Same Everrest B2B2C schema as the canon case (8 tables, seed 42, M0007 the
canonical bulk-wholesale outlier, weekend + November seasonality). This edition
plants a DIFFERENT set of quirks from how-to-eda (the Claude edition), so the
Codex walkthrough digs out new problems instead of rerunning the same five.

CANON kept as real background (re-confirmed by EDA, not "caught"):
  - M0007 'Summit Wholesale Co' bulk-pallet outlier (~59x median order).
  - Weekly weekend lift + November promo spike.

PLANTED QUIRKS (verification checks recall of exactly these six):
1. ORPHAN FOREIGN KEYS - ~2.5% of order_items.product_id and ~1.0% of
   orders.customer_id point to ids that do not exist (a bad ETL join). Pure
   referential-integrity break, invisible to single-table describe().
2. STALE PRICE SNAPSHOT - for orders in Sep-Nov 2025, order_items.unit_price is
   frozen at ~0.82x the current products.price (a catalog snapshot that never
   refreshed). unit_price != catalog price for that window.
3. NEGATIVE PAYMENT LATENCY (timezone bug) - payments for PH-region orders were
   logged in local time while order_ts is UTC, so paid_ts lands ~8h BEFORE
   order_ts: physically impossible negative latency for one region only.
4. DIRTY CATEGORICALS - ~9% of merchants.category rows carry case / whitespace /
   typo variants ('electronics', 'Beauty ', 'Grocary', 'apparel'), inflating
   category cardinality from 8 to ~14. Every category rollup silently splits.
5. BENFORD / ROUND-NUMBER FABRICATION - merchant M0333 'Apex Gadget Bazaar'
   reports order amounts heaped on round hundreds (100, 200, ... 900). The
   leading-digit distribution violates Benford's law - a forensic red flag.
6. DUPLICATE CUSTOMER IDENTITIES - ~800 customers appear twice under different
   customer_id but identical (signup_date, channel_id, region): the same person
   double-counted, inflating channel acquisition numbers.

Run:  python generate_everrest_codex.py   ->  writes ./data/*.csv
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
OUT = Path(__file__).parent / "data"

N_MERCHANTS = 400
N_PRODUCTS = 5_000
N_CUSTOMERS = 20_000
N_ORDERS = 50_000

CATEGORIES = [
    "Home & Living",
    "Electronics",
    "Apparel",
    "Beauty",
    "Sports & Outdoor",
    "Toys & Kids",
    "Grocery",
    "Pet Supplies",
]
TIERS = ["standard", "premium", "enterprise"]
CHANNELS = ["organic", "paid_search", "social", "email", "referral", "affiliate"]
REGIONS = ["SG", "MY", "ID", "TH", "VN", "PH"]
PAY_METHODS = ["card", "wallet", "bank_transfer", "bnpl", "cod"]
RETURN_REASONS = ["damaged", "wrong_item", "quality", "changed_mind", "late_delivery"]

START = pd.Timestamp("2025-07-01")
END = pd.Timestamp("2026-06-30")

# Quirk 4: dirty label variants injected on top of the clean category.
DIRTY_MAP = {
    "Electronics": "electronics",
    "Beauty": "Beauty ",
    "Grocery": "Grocary",
    "Apparel": "apparel",
    "Home & Living": "Home & living",
    "Toys & Kids": "Toys and Kids",
}
FAB_MERCHANT = "M0333"  # Quirk 5: fabricated round-number amounts.


def make_merchants(rng: np.random.Generator) -> pd.DataFrame:
    ids = [f"M{i:04d}" for i in range(1, N_MERCHANTS + 1)]
    df = pd.DataFrame(
        {
            "merchant_id": ids,
            "category": rng.choice(CATEGORIES, N_MERCHANTS),
            "tier": rng.choice(TIERS, N_MERCHANTS, p=[0.65, 0.25, 0.10]),
            "joined_at": START
            - pd.to_timedelta(rng.integers(30, 1200, N_MERCHANTS), unit="D"),
        }
    )
    # Canon: the bulk-pallet outlier merchant.
    df.loc[df.merchant_id == "M0007", ["category", "tier"]] = ["Grocery", "enterprise"]
    df.loc[df.merchant_id == FAB_MERCHANT, ["category", "tier"]] = [
        "Electronics",
        "premium",
    ]
    return df


def dirty_categories(rng: np.random.Generator, df: pd.DataFrame) -> pd.DataFrame:
    """Quirk 4: corrupt ~9% of merchant category labels with variants."""
    corruptible = df.index[
        df.category.isin(DIRTY_MAP) & ~df.merchant_id.isin(["M0007", FAB_MERCHANT])
    ]
    hit = rng.choice(corruptible, size=int(0.09 * len(df)), replace=False)
    df.loc[hit, "category"] = df.loc[hit, "category"].map(DIRTY_MAP)
    return df


def make_products(rng: np.random.Generator, merchants: pd.DataFrame) -> pd.DataFrame:
    # products.category derived from the CLEAN merchant category (built pre-dirty).
    merchant_ids = rng.choice(merchants.merchant_id, N_PRODUCTS)
    cat_map = merchants.set_index("merchant_id").category
    base_price = np.round(np.exp(rng.normal(3.2, 0.9, N_PRODUCTS)), 2)  # ~$25 median
    df = pd.DataFrame(
        {
            "product_id": [f"P{i:05d}" for i in range(1, N_PRODUCTS + 1)],
            "merchant_id": merchant_ids,
            "category": cat_map.loc[merchant_ids].values,
            "price": np.clip(base_price, 1.5, 900),
        }
    )
    # Canon: M0007 sells bulk pallets - price them ~40x.
    m7 = df.merchant_id == "M0007"
    df.loc[m7, "price"] = np.round(df.loc[m7, "price"] * 40, 2)
    return df


def make_customers(rng: np.random.Generator) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "customer_id": [f"C{i:06d}" for i in range(1, N_CUSTOMERS + 1)],
            # Full signup timestamp (to the second) - so a genuine duplicate
            # identity is unmistakable, not a day-level coincidence.
            "signup_date": START
            - pd.to_timedelta(rng.integers(0, 900 * 86_400, N_CUSTOMERS), unit="s"),
            "channel_id": rng.choice(
                CHANNELS, N_CUSTOMERS, p=[0.28, 0.22, 0.18, 0.12, 0.10, 0.10]
            ),
            "region": rng.choice(
                REGIONS, N_CUSTOMERS, p=[0.30, 0.20, 0.20, 0.12, 0.10, 0.08]
            ),
        }
    )
    # Quirk 6: ~800 duplicate identities - same person, new customer_id.
    clones = df.sample(800, random_state=SEED).copy()
    clones["customer_id"] = [f"C9{i:05d}" for i in range(1, len(clones) + 1)]
    return pd.concat([df, clones], ignore_index=True)


def order_timestamps(rng: np.random.Generator, n: int) -> pd.Series:
    """Canon: weekly cycle (weekend lift) + November promo spike (~2.2x)."""
    days = pd.date_range(START, END, freq="D")
    dow_weight = np.where(days.dayofweek >= 5, 1.45, 1.0)
    nov_weight = np.where(days.month == 11, 2.2, 1.0)
    growth = np.linspace(0.85, 1.15, len(days))
    w = dow_weight * nov_weight * growth
    day_idx = rng.choice(len(days), n, p=w / w.sum())
    secs = rng.integers(8 * 3600, 23 * 3600, n)
    return pd.Series(days[day_idx]) + pd.to_timedelta(secs, unit="s")


def make_orders(
    rng: np.random.Generator, customers: pd.DataFrame, merchants: pd.DataFrame
) -> pd.DataFrame:
    real_ids = customers.customer_id.values
    cust = rng.choice(real_ids, N_ORDERS)
    df = pd.DataFrame(
        {
            "order_id": [f"O{i:06d}" for i in range(1, N_ORDERS + 1)],
            "customer_id": cust,
            "merchant_id": rng.choice(merchants.merchant_id, N_ORDERS),
            "order_ts": order_timestamps(rng, N_ORDERS),
            "status": rng.choice(
                ["delivered", "shipped", "paid", "cancelled"],
                N_ORDERS,
                p=[0.78, 0.08, 0.06, 0.08],
            ),
        }
    )
    # Quirk 1a: ~1.0% orders reference a customer_id that does not exist.
    orphan = rng.choice(df.index, size=int(0.010 * N_ORDERS), replace=False)
    df.loc[orphan, "customer_id"] = [f"C8{i:05d}" for i in range(len(orphan))]
    return df.sort_values("order_ts", kind="stable").reset_index(drop=True)


def make_order_items(
    rng: np.random.Generator, orders: pd.DataFrame, products: pd.DataFrame
) -> pd.DataFrame:
    n_items = rng.choice(
        [1, 2, 3, 4, 5, 6], len(orders), p=[0.42, 0.27, 0.15, 0.08, 0.05, 0.03]
    )
    order_rep = orders.loc[
        orders.index.repeat(n_items), ["order_id", "merchant_id", "order_ts"]
    ]
    prod_by_merchant = products.groupby("merchant_id").product_id.apply(np.array)
    prices = products.set_index("product_id").price

    picked = [
        rng.choice(prod_by_merchant.get(m, products.product_id.values))
        for m in order_rep.merchant_id
    ]
    unit_price = prices.loc[picked].values.astype(float)

    df = pd.DataFrame(
        {
            "order_id": order_rep.order_id.values,
            "product_id": picked,
            "qty": rng.choice([1, 1, 1, 2, 2, 3], len(order_rep)),
            "unit_price": unit_price,
            "discount": np.round(
                rng.choice([0, 0, 0, 0.05, 0.10, 0.20], len(order_rep)), 2
            ),
            "order_ts": order_rep.order_ts.values,
        }
    )

    # Quirk 2: stale price snapshot for Sep-Nov 2025 -> unit_price frozen at 0.82x.
    ts = pd.to_datetime(df.order_ts)
    stale = (ts >= "2025-09-01") & (ts < "2025-12-01")
    df.loc[stale, "unit_price"] = np.round(df.loc[stale, "unit_price"] * 0.82, 2)

    # Quirk 1b: ~2.5% of line items reference a non-existent product_id.
    orphan = rng.choice(df.index, size=int(0.025 * len(df)), replace=False)
    df.loc[orphan, "product_id"] = [f"P9{i:04d}" for i in range(len(orphan))]

    return df.drop(columns="order_ts").reset_index(drop=True)


def make_payments(
    rng: np.random.Generator,
    orders: pd.DataFrame,
    order_items: pd.DataFrame,
    customers: pd.DataFrame,
) -> pd.DataFrame:
    amounts = (
        order_items.assign(net=lambda d: d.qty * d.unit_price * (1 - d.discount))
        .groupby("order_id")
        .net.sum()
        .round(2)
    )
    paid = orders[orders.status != "cancelled"].copy()
    df = pd.DataFrame(
        {
            "payment_id": [f"PAY{i:06d}" for i in range(1, len(paid) + 1)],
            "order_id": paid.order_id.values,
            "method": rng.choice(
                PAY_METHODS, len(paid), p=[0.38, 0.27, 0.12, 0.13, 0.10]
            ),
            "amount": amounts.reindex(paid.order_id).fillna(0.0).values,
            "paid_ts": paid.order_ts.values
            + pd.to_timedelta(rng.integers(60, 3600, len(paid)), unit="s"),
            "merchant_id": paid.merchant_id.values,
            "customer_id": paid.customer_id.values,
        }
    )

    # Quirk 3: PH-region payments logged in local time (UTC+8) -> paid_ts ~8h early.
    region = customers.set_index("customer_id").region
    pay_region = region.reindex(df.customer_id).values
    ph = pay_region == "PH"
    df.loc[ph, "paid_ts"] = df.loc[ph, "paid_ts"] - pd.Timedelta(hours=8)

    # Quirk 5: fabricated merchant reports round-hundred amounts.
    fab = df.merchant_id == FAB_MERCHANT
    df.loc[fab, "amount"] = rng.choice(
        [100, 200, 300, 400, 500, 600, 700, 800, 900], fab.sum()
    ).astype(float)

    return df.drop(columns=["merchant_id", "customer_id"])


def make_returns(
    rng: np.random.Generator, orders: pd.DataFrame, merchants: pd.DataFrame
) -> pd.DataFrame:
    delivered = orders[orders.status == "delivered"].copy()
    cat = merchants.set_index("merchant_id").category
    order_cat = cat.reindex(delivered.merchant_id).values
    # Mild real signal: Electronics returns a bit more (not a planted quirk).
    p_ret = np.where(pd.Series(order_cat).str.contains("lectronic").values, 0.09, 0.05)
    returned = delivered[rng.random(len(delivered)) < p_ret]
    return pd.DataFrame(
        {
            "return_id": [f"R{i:05d}" for i in range(1, len(returned) + 1)],
            "order_id": returned.order_id.values,
            "reason": rng.choice(
                RETURN_REASONS, len(returned), p=[0.22, 0.18, 0.34, 0.16, 0.10]
            ),
            "return_ts": returned.order_ts.values
            + pd.to_timedelta(rng.integers(2, 21, len(returned)), unit="D"),
        }
    )


def main() -> None:
    rng = np.random.default_rng(SEED)
    OUT.mkdir(exist_ok=True)

    merchants = make_merchants(rng)
    products = make_products(rng, merchants)  # derived from CLEAN categories
    merchants = dirty_categories(rng, merchants)  # then corrupt labels (quirk 4)
    customers = make_customers(rng)
    channels = pd.DataFrame(
        {
            "channel_id": CHANNELS,
            "name": [c.replace("_", " ").title() for c in CHANNELS],
        }
    )
    orders = make_orders(rng, customers, merchants)
    order_items = make_order_items(rng, orders, products)
    payments = make_payments(rng, orders, order_items, customers)
    returns = make_returns(rng, orders, merchants)

    tables = {
        "merchants": merchants,
        "products": products,
        "customers": customers,
        "channels": channels,
        "orders": orders,
        "order_items": order_items,
        "payments": payments,
        "returns": returns,
    }
    total = 0
    for name, df in tables.items():
        df.to_csv(OUT / f"{name}.csv", index=False)
        total += len(df)
        print(f"{name:12s} {len(df):>8,d} rows")
    print(f"{'TOTAL':12s} {total:>8,d} rows  (seed={SEED})")


if __name__ == "__main__":
    main()
