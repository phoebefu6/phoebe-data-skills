"""Everrest lineage - STAGE 0: the raw operational dump.

This is how ingestion actually arrives: three source systems, denormalized, with
their own key formats and their own defects. The Infra flagship
(how-to-schema-and-warehouse) turns this mess into a queryable star schema.

Four raw exports (seed 42) from four source systems:
  raw_transactions.csv       - app DB export, one wide row per order line
  raw_products_export.csv    - product catalog master (current prices)
  raw_merchants_extract.json - merchant master from a 2nd system (MER-#### keys)
  raw_payments_export.csv    - payment processor export

PLANTED QUIRKS (all live in RAW - they are ingestion problems; the warehouse
build is what resolves them; verification checks recall of exactly these six):
1. ORPHAN FOREIGN KEYS - ~2.5% of transaction product_id and ~1.0% of order
   customer_id reference ids that do not exist in any master.
2. DIRTY CATEGORICALS - merchant category arrives as 14 label variants for 8 real
   categories ('electronics', 'Beauty ', 'Grocary', 'apparel', ...).
3. HETEROGENEOUS KEYS - the merchant master uses 'MER-0001' while transactions use
   'M0001'; they must be reconciled or every merchant join fails.
4. TIMEZONE BUG - PH-region payments are logged in local time (UTC+8), so paid_at
   lands ~8h BEFORE the order timestamp (impossible negative latency).
5. ROUND-NUMBER FABRICATION - merchant M0333 'Apex Gadget Bazaar' reports payment
   amounts heaped on round hundreds (Benford red flag).
6. DUPLICATE IDENTITIES - ~800 customers appear under two ids with identical
   signup timestamp, channel and region (double-counted people).

Plus canon (kept, not a defect): M0007 bulk-wholesale outlier, weekend + November
seasonality, 8 categories, SEA regions.

Run:  python generate_raw.py   ->  writes ./raw/*
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
RAW = Path(__file__).parent / "raw"

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
START = pd.Timestamp("2025-07-01")
END = pd.Timestamp("2026-06-30")

# Quirk 2: dirty label variants layered onto the clean category.
DIRTY_MAP = {
    "Electronics": "electronics",
    "Beauty": "Beauty ",
    "Grocery": "Grocary",
    "Apparel": "apparel",
    "Home & Living": "Home & living",
    "Toys & Kids": "Toys and Kids",
}
FAB_MERCHANT = "M0333"


def build_truth(rng: np.random.Generator) -> dict[str, pd.DataFrame]:
    # merchants (clean categories first; dirtied only in the extract)
    merchants = pd.DataFrame(
        {
            "merchant_id": [f"M{i:04d}" for i in range(1, N_MERCHANTS + 1)],
            "category": rng.choice(CATEGORIES, N_MERCHANTS),
            "tier": rng.choice(TIERS, N_MERCHANTS, p=[0.65, 0.25, 0.10]),
            "onboarded_at": START
            - pd.to_timedelta(rng.integers(30, 1200, N_MERCHANTS), unit="D"),
        }
    )
    merchants.loc[merchants.merchant_id == "M0007", ["category", "tier"]] = [
        "Grocery",
        "enterprise",
    ]
    merchants.loc[merchants.merchant_id == FAB_MERCHANT, ["category", "tier"]] = [
        "Electronics",
        "premium",
    ]

    # products (M0007 bulk-priced)
    prod_merchant = rng.choice(merchants.merchant_id, N_PRODUCTS)
    price = np.clip(np.round(np.exp(rng.normal(3.2, 0.9, N_PRODUCTS)), 2), 1.5, 900)
    products = pd.DataFrame(
        {
            "product_id": [f"P{i:05d}" for i in range(1, N_PRODUCTS + 1)],
            "merchant_id": prod_merchant,
            "price": price,
        }
    )
    m7 = products.merchant_id == "M0007"
    products.loc[m7, "price"] = np.round(products.loc[m7, "price"] * 40, 2)

    # customers (+ 800 duplicate identities: quirk 6)
    customers = pd.DataFrame(
        {
            "customer_id": [f"C{i:06d}" for i in range(1, N_CUSTOMERS + 1)],
            "signup_ts": START
            - pd.to_timedelta(rng.integers(0, 900 * 86_400, N_CUSTOMERS), unit="s"),
            "channel": rng.choice(
                CHANNELS, N_CUSTOMERS, p=[0.28, 0.22, 0.18, 0.12, 0.10, 0.10]
            ),
            "region": rng.choice(
                REGIONS, N_CUSTOMERS, p=[0.30, 0.20, 0.20, 0.12, 0.10, 0.08]
            ),
        }
    )
    clones = customers.sample(800, random_state=SEED).copy()
    clones["customer_id"] = [f"C9{i:05d}" for i in range(1, len(clones) + 1)]
    customers = pd.concat([customers, clones], ignore_index=True)

    # orders (seasonality + 1% orphan customer_id: quirk 1a)
    days = pd.date_range(START, END, freq="D")
    w = (
        np.where(days.dayofweek >= 5, 1.45, 1.0)
        * np.where(days.month == 11, 2.2, 1.0)
        * np.linspace(0.85, 1.15, len(days))
    )
    day_idx = rng.choice(len(days), N_ORDERS, p=w / w.sum())
    order_ts = pd.Series(days[day_idx]) + pd.to_timedelta(
        rng.integers(8 * 3600, 23 * 3600, N_ORDERS), unit="s"
    )
    orders = pd.DataFrame(
        {
            "order_id": [f"O{i:06d}" for i in range(1, N_ORDERS + 1)],
            "customer_id": rng.choice(customers.customer_id, N_ORDERS),
            "merchant_id": rng.choice(merchants.merchant_id, N_ORDERS),
            "order_ts": order_ts,
            "status": rng.choice(
                ["delivered", "shipped", "paid", "cancelled"],
                N_ORDERS,
                p=[0.78, 0.08, 0.06, 0.08],
            ),
        }
    )
    orphan_o = rng.choice(orders.index, int(0.010 * N_ORDERS), replace=False)
    orders.loc[orphan_o, "customer_id"] = [f"C8{i:05d}" for i in range(len(orphan_o))]

    # order_items (stale price Sep-Nov: quirk implied; 2.5% orphan product: 1b)
    n_items = rng.choice(
        [1, 2, 3, 4, 5, 6], N_ORDERS, p=[0.42, 0.27, 0.15, 0.08, 0.05, 0.03]
    )
    rep = orders.loc[
        orders.index.repeat(n_items), ["order_id", "merchant_id", "order_ts"]
    ].reset_index(drop=True)
    prod_by_m = products.groupby("merchant_id").product_id.apply(np.array)
    prices = products.set_index("product_id").price
    picked = [
        rng.choice(prod_by_m.get(m, products.product_id.values))
        for m in rep.merchant_id
    ]
    items = pd.DataFrame(
        {
            "order_id": rep.order_id,
            "merchant_id": rep.merchant_id,
            "order_ts": rep.order_ts,
            "product_id": picked,
            "qty": rng.choice([1, 1, 1, 2, 2, 3], len(rep)),
            "unit_price": prices.loc[picked].values.astype(float),
            "discount": np.round(rng.choice([0, 0, 0, 0.05, 0.10, 0.20], len(rep)), 2),
        }
    )
    # stale Sep-Nov snapshot at 0.82x
    ts = pd.to_datetime(items.order_ts)
    stale = (ts >= "2025-09-01") & (ts < "2025-12-01")
    items.loc[stale, "unit_price"] = np.round(items.loc[stale, "unit_price"] * 0.82, 2)
    # orphan product ids
    orphan_i = rng.choice(items.index, int(0.025 * len(items)), replace=False)
    items.loc[orphan_i, "product_id"] = [f"P9{i:04d}" for i in range(len(orphan_i))]

    # payments (TZ bug + fabrication)
    items["net"] = items.qty * items.unit_price * (1 - items.discount)
    amt = items.groupby("order_id").net.sum().round(2)
    paid = orders[orders.status != "cancelled"].copy()
    pay = pd.DataFrame(
        {
            "order_id": paid.order_id.values,
            "merchant_id": paid.merchant_id.values,
            "customer_id": paid.customer_id.values,
            "method": rng.choice(
                PAY_METHODS, len(paid), p=[0.38, 0.27, 0.12, 0.13, 0.10]
            ),
            "amount": amt.reindex(paid.order_id).fillna(0.0).values,
            "paid_at": paid.order_ts.values
            + pd.to_timedelta(rng.integers(60, 3600, len(paid)), unit="s"),
        }
    )
    region = customers.set_index("customer_id").region
    pay_region = region.reindex(pay.customer_id).values
    ph = pay_region == "PH"
    pay.loc[ph, "paid_at"] = pay.loc[ph, "paid_at"] - pd.Timedelta(hours=8)
    fab = pay.merchant_id == FAB_MERCHANT
    pay.loc[fab, "amount"] = rng.choice(
        [100, 200, 300, 400, 500, 600, 700, 800, 900], fab.sum()
    ).astype(float)

    return {
        "merchants": merchants,
        "products": products,
        "customers": customers,
        "orders": orders,
        "items": items,
        "pay": pay,
    }


def main() -> None:
    rng = np.random.default_rng(SEED)
    RAW.mkdir(parents=True, exist_ok=True)
    t = build_truth(rng)
    merchants, products, customers = t["merchants"], t["products"], t["customers"]
    orders, items, pay = t["orders"], t["items"], t["pay"]

    # ---- raw_transactions.csv : one wide, denormalized row per order line ----
    cust = customers.set_index("customer_id")
    txn = items.merge(
        orders[["order_id", "customer_id", "status"]], on="order_id", how="left"
    )
    txn["cust_signup_ts"] = cust.signup_ts.reindex(txn.customer_id).values
    txn["cust_channel"] = cust.channel.reindex(txn.customer_id).values
    txn["cust_region"] = cust.region.reindex(txn.customer_id).values
    # dirty category from merchant (quirk 2), ~9% variant labels
    mcat = merchants.set_index("merchant_id").category.copy()
    dirty_idx = rng.choice(
        mcat.index[mcat.isin(DIRTY_MAP) & ~mcat.index.isin(["M0007", FAB_MERCHANT])],
        size=int(0.09 * len(mcat)),
        replace=False,
    )
    mcat.loc[dirty_idx] = mcat.loc[dirty_idx].map(DIRTY_MAP)
    txn["category_raw"] = mcat.reindex(txn.merchant_id).values
    # mixed status casing (quirk: dirty strings)
    flip = rng.random(len(txn)) < 0.20
    txn.loc[flip, "status"] = txn.loc[flip, "status"].str.capitalize()
    txn = txn.rename(columns={"order_ts": "order_ts_utc"})
    txn.insert(0, "txn_id", [f"T{i:07d}" for i in range(1, len(txn) + 1)])
    txn_cols = [
        "txn_id",
        "order_id",
        "order_ts_utc",
        "status",
        "customer_id",
        "cust_signup_ts",
        "cust_channel",
        "cust_region",
        "merchant_id",
        "category_raw",
        "product_id",
        "qty",
        "unit_price",
        "discount",
    ]
    txn[txn_cols].to_csv(RAW / "raw_transactions.csv", index=False)

    # ---- raw_products_export.csv : product catalog master (current prices) ----
    # Clean catalog of the real 5,000 products. Transaction product_ids not found
    # here are orphans (quirk 1); unit_price != catalog_price reveals the stale
    # Sep-Nov snapshot.
    products.rename(columns={"price": "catalog_price"})[
        ["product_id", "merchant_id", "catalog_price"]
    ].to_csv(RAW / "raw_products_export.csv", index=False)

    # ---- raw_merchants_extract.json : 2nd system, MER-#### keys, dirty cats ----
    ext = merchants.copy()
    ext["merchant_key"] = ext.merchant_id.str.replace("M", "MER-", regex=False)
    ext_cat = merchants.set_index("merchant_id").category.copy()
    ext_dirty = rng.choice(
        ext_cat.index[
            ext_cat.isin(DIRTY_MAP) & ~ext_cat.index.isin(["M0007", FAB_MERCHANT])
        ],
        size=int(0.09 * len(ext_cat)),
        replace=False,
    )
    ext_cat.loc[ext_dirty] = ext_cat.loc[ext_dirty].map(DIRTY_MAP)
    records = [
        {
            "merchant_key": r.merchant_key,
            "legacy_id": r.merchant_id,
            "category": ext_cat[r.merchant_id],
            "tier": r.tier,
            "onboarded": pd.Timestamp(r.onboarded_at).strftime("%Y-%m-%d"),
        }
        for r in ext.itertuples()
    ]
    (RAW / "raw_merchants_extract.json").write_text(json.dumps(records, indent=2))

    # ---- raw_payments_export.csv : processor export ----
    pay_out = pay.copy()
    pay_out.insert(0, "pmt_ref", [f"PMT-{i:06d}" for i in range(1, len(pay_out) + 1)])
    pay_out = pay_out.rename(columns={"amount": "amount_reported"})
    pay_out[["pmt_ref", "order_id", "method", "amount_reported", "paid_at"]].to_csv(
        RAW / "raw_payments_export.csv", index=False
    )

    print(f"raw_transactions.csv      {len(txn):>8,d} rows")
    print(f"raw_merchants_extract.json{len(records):>8,d} records")
    print(f"raw_payments_export.csv   {len(pay_out):>8,d} rows")
    print(f"(seed={SEED})")


if __name__ == "__main__":
    main()
