"""Everrest lineage - the ENTERPRISE REALITY: 9 servers, 8,600 tables, drift.

Everrest did not grow one clean warehouse. Every new server setup cloned the
whole schema, so the same logical table now lives as many near-identical physical
copies across 9 server-schemas - and they have quietly drifted apart. The data
dictionary only ever documented the ~1,300 logical tables, so most physical tables
are undocumented clones, and merging any table into one truth first requires a
schema diff, because a column can exist on only one server.

This generator simulates that estate (seed 42):
  data/catalog.csv          - one row per PHYSICAL table (~8,600) across 9 schemas
  data/columns.csv          - one row per (schema, logical_id, column, dtype)
  data/data_dictionary.csv  - the 1,300 documented LOGICAL tables

PLANTED REALITIES (what the consolidation skill must surface):
1. SCALE: ~1,300 logical tables replicated across 9 server-schemas (partial,
   avg ~6.6 copies each) => ~8,600 physical tables.
2. DOC GAP: the dictionary covers the 1,300 logical tables => only ~15% of the
   8,600 physical tables are documented; the rest are undocumented clones.
3. COLUMN-PRESENCE DRIFT: each copy includes a random subset of optional columns
   plus occasional server-unique columns, so many columns exist on only ONE
   server. Merging needs a superset, not a blind UNION.
4. TYPE DRIFT (bonus): a small share of columns carry a different dtype on one
   server than the others - a silent merge hazard.

Run:  python generate_catalog.py   ->  writes ./data/*
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
OUT = Path(__file__).parent / "data"

N_LOGICAL = 1_300
N_SERVERS = 9
SCHEMAS = [f"srv{n:02d}" for n in range(1, N_SERVERS + 1)]
REPL_P = 0.735  # per-server presence prob -> mean ~6.6 copies -> ~8,600 physical

DOMAINS = [
    "orders",
    "customers",
    "merchants",
    "products",
    "payments",
    "returns",
    "inventory",
    "shipping",
    "marketing",
    "finance",
    "support",
    "catalog",
]
CORE = ["id", "created_at", "updated_at", "status", "source_system"]
CORE_TYPES = ["BIGINT", "TIMESTAMP", "TIMESTAMP", "VARCHAR", "VARCHAR"]
OPTIONAL_POOL = [
    "region",
    "currency",
    "channel",
    "tax_code",
    "discount_pct",
    "notes",
    "external_ref",
    "gdpr_consent",
    "is_deleted",
    "priority",
    "segment",
    "loyalty_tier",
    "warehouse_id",
    "carrier",
    "risk_score",
    "device_id",
]
DTYPES = ["INT", "BIGINT", "VARCHAR", "DECIMAL", "TIMESTAMP", "DATE", "BOOLEAN"]
# plausible type drift only (a widening / near-equivalent), not random garbage
COMPAT = {
    "INT": "BIGINT",
    "BIGINT": "INT",
    "VARCHAR": "TEXT",
    "DECIMAL": "DOUBLE",
    "DATE": "TIMESTAMP",
    "TIMESTAMP": "DATE",
    "BOOLEAN": "INT",
}


def main() -> None:
    rng = np.random.default_rng(SEED)
    OUT.mkdir(parents=True, exist_ok=True)

    logical = pd.DataFrame(
        {
            "logical_id": [f"L{i:04d}" for i in range(1, N_LOGICAL + 1)],
            "domain": rng.choice(DOMAINS, N_LOGICAL),
        }
    )
    logical["logical_name"] = [
        f"{d}_{i:04d}" for i, d in zip(range(1, N_LOGICAL + 1), logical.domain)
    ]

    # Per logical table: a base set of optional columns (shared intent) + the
    # canonical dtype for each column. Drift is applied per physical copy.
    base_opt = {}
    canon_type = {}
    for lid in logical.logical_id:
        k = int(rng.integers(3, 11))
        opts = list(rng.choice(OPTIONAL_POOL, size=k, replace=False))
        base_opt[lid] = opts
        canon_type[lid] = {c: t for c, t in zip(CORE, CORE_TYPES)}
        for c in opts:
            canon_type[lid][c] = str(rng.choice(DTYPES))

    catalog_rows = []
    column_rows = []
    for lid, dom, lname in logical.itertuples(index=False):
        # which servers host a copy (at least one)
        present = rng.random(N_SERVERS) < REPL_P
        if not present.any():
            present[rng.integers(N_SERVERS)] = True
        for si, host in enumerate(present):
            if not host:
                continue
            schema = SCHEMAS[si]
            cols = list(CORE)
            # each optional column included on this server with prob 0.85 -> drift
            for c in base_opt[lid]:
                if rng.random() < 0.85:
                    cols.append(c)
            # server-unique column sometimes (a true singleton)
            if rng.random() < 0.12:
                cols.append(f"{schema}_ext_{rng.integers(1, 4)}")
            for c in cols:
                dtype = canon_type[lid].get(c, "VARCHAR")
                # type drift: rare, and only to a plausible near-equivalent type
                if c in canon_type[lid] and rng.random() < 0.015:
                    dtype = COMPAT.get(dtype, dtype)
                column_rows.append((schema, lid, c, dtype))
            catalog_rows.append(
                (schema, f"{schema}.{lname}", lid, lname, dom, len(cols))
            )

    catalog = pd.DataFrame(
        catalog_rows,
        columns=[
            "schema",
            "physical_name",
            "logical_id",
            "logical_name",
            "domain",
            "n_columns",
        ],
    )
    columns = pd.DataFrame(
        column_rows, columns=["schema", "logical_id", "column_name", "dtype"]
    )
    # the data dictionary documents the LOGICAL tables only
    data_dict = logical.assign(
        description=lambda d: "Documented logical definition for " + d.logical_name,
        owner=rng.choice(
            ["data-eng", "analytics", "finance-bi", "platform"], len(logical)
        ),
    )[["logical_id", "logical_name", "domain", "description", "owner"]]

    catalog.to_csv(OUT / "catalog.csv", index=False)
    columns.to_csv(OUT / "columns.csv", index=False)
    data_dict.to_csv(OUT / "data_dictionary.csv", index=False)

    print(f"logical tables      {N_LOGICAL:>8,d}")
    print(f"physical tables     {len(catalog):>8,d}  across {N_SERVERS} schemas")
    print(f"column records      {len(columns):>8,d}")
    print(f"documented (dict)   {len(data_dict):>8,d}  logical tables")
    print(f"avg copies / logical {len(catalog)/N_LOGICAL:>7.1f}   (seed={SEED})")


if __name__ == "__main__":
    main()
