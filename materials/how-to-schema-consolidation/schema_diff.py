"""Reusable schema-diff engine: compare one logical table across all servers.

The core of consolidation. Before you can merge N drifted copies of a table into
one, you must know exactly how they differ - which columns are everywhere, which
exist on only one server, and where a column's dtype disagrees. This module is
importable (used by analyze_catalog.py) and runnable standalone.

Run:  python schema_diff.py L0042
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

DATA = Path(__file__).parent / "data"


def diff_table(columns: pd.DataFrame, logical_id: str) -> dict:
    """Compare a logical table's columns across every server that hosts it."""
    sub = columns[columns.logical_id == logical_id]
    if sub.empty:
        raise ValueError(f"no such logical table: {logical_id}")
    servers = sorted(sub.schema.unique())
    # presence matrix: column x server (dtype where present, else "")
    matrix = sub.pivot_table(
        index="column_name",
        columns="schema",
        values="dtype",
        aggfunc="first",
    ).reindex(columns=servers)
    present = matrix.notna()
    n_present = present.sum(axis=1)
    superset = list(matrix.index)  # union of all columns
    common = list(n_present[n_present == len(servers)].index)  # in every server
    singletons = list(n_present[n_present == 1].index)  # exist on ONE server only
    # type drift: a column carrying >1 distinct dtype across servers
    type_conflicts = {
        c: sorted(matrix.loc[c].dropna().unique())
        for c in matrix.index
        if matrix.loc[c].dropna().nunique() > 1
    }
    return {
        "logical_id": logical_id,
        "servers": servers,
        "matrix": matrix,
        "present": present,
        "n_present": n_present,
        "superset": superset,
        "common": common,
        "singletons": singletons,
        "type_conflicts": type_conflicts,
        "has_drift": len(superset) > len(common) or bool(type_conflicts),
    }


def merged_ddl(d: dict, table: str = "merged") -> str:
    """A superset CREATE TABLE - union of columns; conflicts widened to VARCHAR."""
    lines = [f"CREATE TABLE {table} ("]
    lines.append(
        "    server_source VARCHAR,   -- lineage: which server this row came from"
    )
    for c in d["superset"]:
        types = d["matrix"].loc[c].dropna().unique()
        dtype = types[0] if len(types) == 1 else "VARCHAR"  # widen on conflict
        flags = []
        if c in d["singletons"]:
            flags.append("only 1 server")
        if c in d["type_conflicts"]:
            flags.append("TYPE CONFLICT " + "/".join(d["type_conflicts"][c]))
        note = f"   -- {', '.join(flags)}" if flags else ""
        lines.append(f"    {c} {dtype},{note}")
    lines.append(");")
    return "\n".join(lines)


if __name__ == "__main__":
    cols = pd.read_csv(DATA / "columns.csv")
    lid = sys.argv[1] if len(sys.argv) > 1 else cols.logical_id.iloc[0]
    d = diff_table(cols, lid)
    print(f"{lid}: {len(d['servers'])} servers, {len(d['superset'])} distinct columns")
    print(f"  common to all : {len(d['common'])}")
    print(f"  singletons    : {d['singletons']}")
    print(f"  type conflicts: {d['type_conflicts']}")
    print("\n" + merged_ddl(d))
