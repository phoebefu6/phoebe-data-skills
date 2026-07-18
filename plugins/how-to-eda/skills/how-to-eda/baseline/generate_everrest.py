"""Everrest sample data generator.

Everrest is a fictional B2B2C retail platform: brands and merchants sell to
consumers through one marketplace. This script builds all 8 tables with a
fixed seed so every run is identical.

PLANTED QUIRKS (verification checks recall of exactly these five):
1. MISSING NOT AT RANDOM - payments.method is null for ~8% of rows overall,
   but the nulls concentrate in the 'affiliate' channel (legacy tracker
   drops the field), not spread evenly.
2. OUTLIER MERCHANT - merchant M0007 ('Summit Wholesale Co') sells bulk
   pallets: 40x prices x bulk quantities puts its median order ~59x the
   platform median.
3. DUPLICATE ROWS - ~600 orders double-fired by a retry bug in March 2026:
   exact duplicate rows in `orders` (same order_id appears twice).
4. SEASONALITY - demand has a weekly cycle (weekend lift) plus a November
   promo spike (~2.2x).
5. SUSPICIOUS SEGMENT - 'premium' tier merchants have ~4x the return rate
   of other tiers (quality issue hiding in aggregate return numbers).

Run:  python generate_everrest.py   ->  writes ./data/*.csv
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
    # Quirk 2: the bulk-pallet outlier merchant.
    df.loc[df.merchant_id == "M0007", ["category", "tier"]] = ["Grocery", "enterprise"]
    return df


def make_products(rng: np.random.Generator, merchants: pd.DataFrame) -> pd.DataFrame:
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
    # Quirk 2: M0007 sells bulk pallets - price them ~40x.
    m7 = df.merchant_id == "M0007"
    df.loc[m7, "price"] = np.round(df.loc[m7, "price"] * 40, 2)
    return df


def make_customers(rng: np.random.Generator) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "customer_id": [f"C{i:06d}" for i in range(1, N_CUSTOMERS + 1)],
            "signup_date": START
            - pd.to_timedelta(rng.integers(0, 900, N_CUSTOMERS), unit="D"),
            "channel_id": rng.choice(
                CHANNELS, N_CUSTOMERS, p=[0.28, 0.22, 0.18, 0.12, 0.10, 0.10]
            ),
            "region": rng.choice(
                REGIONS, N_CUSTOMERS, p=[0.30, 0.20, 0.20, 0.12, 0.10, 0.08]
            ),
        }
    )


def order_timestamps(rng: np.random.Generator, n: int) -> pd.Series:
    """Quirk 4: weekly cycle (weekend lift) + November promo spike (~2.2x)."""
    days = pd.date_range(START, END, freq="D")
    dow_weight = np.where(days.dayofweek >= 5, 1.45, 1.0)  # weekend lift
    nov_weight = np.where(days.month == 11, 2.2, 1.0)  # 11.11 season
    growth = np.linspace(0.85, 1.15, len(days))  # mild YoY growth
    w = dow_weight * nov_weight * growth
    day_idx = rng.choice(len(days), n, p=w / w.sum())
    secs = rng.integers(8 * 3600, 23 * 3600, n)  # store hours
    return pd.Series(days[day_idx]) + pd.to_timedelta(secs, unit="s")


def make_orders(
    rng: np.random.Generator, customers: pd.DataFrame, merchants: pd.DataFrame
) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "order_id": [f"O{i:06d}" for i in range(1, N_ORDERS + 1)],
            "customer_id": rng.choice(customers.customer_id, N_ORDERS),
            "merchant_id": rng.choice(merchants.merchant_id, N_ORDERS),
            "order_ts": order_timestamps(rng, N_ORDERS),
            "status": rng.choice(
                ["delivered", "shipped", "paid", "cancelled"],
                N_ORDERS,
                p=[0.78, 0.08, 0.06, 0.08],
            ),
        }
    )
    # Quirk 3: retry bug double-fires ~600 March-2026 orders (exact dup rows).
    march = df[df.order_ts.dt.to_period("M") == "2026-03"]
    dupes = march.sample(600, random_state=SEED)
    return (
        pd.concat([df, dupes], ignore_index=True)
        .sort_values("order_ts", kind="stable")
        .reset_index(drop=True)
    )


def make_order_items(
    rng: np.random.Generator, orders: pd.DataFrame, products: pd.DataFrame
) -> pd.DataFrame:
    # 1-6 items per order, skewed small.
    n_items = rng.choice(
        [1, 2, 3, 4, 5, 6], len(orders), p=[0.42, 0.27, 0.15, 0.08, 0.05, 0.03]
    )
    order_rep = orders.loc[orders.index.repeat(n_items), ["order_id", "merchant_id"]]

    # Items come from the order's merchant.
    prod_by_merchant = products.groupby("merchant_id").product_id.apply(np.array)
    prices = products.set_index("product_id").price

    picked = [
        rng.choice(prod_by_merchant.get(m, products.product_id.values))
        for m in order_rep.merchant_id
    ]
    df = pd.DataFrame(
        {
            "order_id": order_rep.order_id.values,
            "product_id": picked,
            "qty": rng.choice([1, 1, 1, 2, 2, 3], len(order_rep)),
            "unit_price": prices.loc[picked].values,
            "discount": np.round(
                rng.choice([0, 0, 0, 0.05, 0.10, 0.20], len(order_rep)), 2
            ),
        }
    )
    return df.reset_index(drop=True)


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
    paid = orders[orders.status != "cancelled"].drop_duplicates("order_id")
    df = pd.DataFrame(
        {
            "payment_id": [f"PAY{i:06d}" for i in range(1, len(paid) + 1)],
            "order_id": paid.order_id.values,
            "method": rng.choice(
                PAY_METHODS, len(paid), p=[0.38, 0.27, 0.12, 0.13, 0.10]
            ),
            "amount": amounts.reindex(paid.order_id).fillna(0).values,
            "paid_ts": paid.order_ts.values
            + pd.to_timedelta(rng.integers(60, 3600, len(paid)), unit="s"),
        }
    )
    # Quirk 1: affiliate-channel tracker drops `method` -> nulls concentrate there.
    channel = customers.set_index("customer_id").channel_id
    order_channel = channel.loc[paid.customer_id].values
    p_null = np.where(order_channel == "affiliate", 0.55, 0.035)
    df.loc[rng.random(len(df)) < p_null, "method"] = np.nan
    return df


def make_returns(
    rng: np.random.Generator, orders: pd.DataFrame, merchants: pd.DataFrame
) -> pd.DataFrame:
    delivered = orders[orders.status == "delivered"].drop_duplicates("order_id")
    tier = merchants.set_index("merchant_id").tier
    order_tier = tier.loc[delivered.merchant_id].values
    # Quirk 5: premium tier returns ~4x baseline.
    p_ret = np.where(order_tier == "premium", 0.16, 0.04)
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
    products = make_products(rng, merchants)
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
