"""The BEFORE: what happens when you skip modeling and query the raw dump.

This is the naive first pass the expert panel tore into. It runs clean and returns
plausible-looking numbers - which is exactly the danger. Every defect here is fixed
by the star schema in warehouse.sql (the AFTER).

Run:  python naive_query.py
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb

os.chdir(Path(__file__).parent)
con = duckdb.connect()
con.execute(
    "CREATE TABLE t AS SELECT * FROM read_csv_auto('raw/raw_transactions.csv', header=true)"
)
con.execute(
    "CREATE TABLE p AS SELECT * FROM read_csv_auto('raw/raw_payments_export.csv', header=true)"
)
con.execute(
    "CREATE TABLE m AS SELECT * FROM read_json_auto('raw/raw_merchants_extract.json')"
)

# FLAW 1: revenue by the RAW category label - dirty variants split every bucket.
print("Revenue by category (naive, raw label):")
print(
    con.execute(
        "SELECT category_raw, round(sum(qty*unit_price*(1-discount))) rev "
        "FROM t GROUP BY 1 ORDER BY rev DESC"
    )
    .df()
    .to_string(index=False)
)

# FLAW 2: join transactions to the merchant master on merchant_id - FAILS,
# because the master uses 'MER-0001' keys, not 'M0001'. Silent zero matches.
matched = con.execute(
    "SELECT count(*) FROM t JOIN m ON t.merchant_id = m.merchant_key"
).fetchone()[0]
print(f"\nRows joined to merchant master on merchant_id = merchant_key: {matched}")
print("  -> 0 matches: heterogeneous keys, the whole merchant join silently fails.")

# FLAW 3: total revenue includes cancelled orders + orphan lines, and payment
# amounts are taken at face value (fabrication + timezone never checked).
naive_rev = con.execute("SELECT round(sum(amount_reported)) FROM p").fetchone()[0]
print(
    f"\nNaive total 'revenue' from raw payments (incl. fabricated M0333): ${naive_rev:,.0f}"
)

# FLAW 4: distinct customers counted from raw ids - duplicates inflate the base.
naive_cust = con.execute("SELECT count(DISTINCT customer_id) FROM t").fetchone()[0]
print(f"Naive distinct customers (raw ids, duplicates not collapsed): {naive_cust:,}")
print("\nAll four fixed in warehouse.sql - see build_warehouse.py for the AFTER.")
