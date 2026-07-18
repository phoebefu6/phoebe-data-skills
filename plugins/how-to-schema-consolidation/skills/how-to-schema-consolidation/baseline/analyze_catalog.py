"""Analyze the 9-server estate: coverage, redundancy, drift, and a schema diff.

Reads the simulated catalog and renders the consolidation story:
 - documentation coverage gap (1,300 documented vs ~8,600 physical)
 - clone redundancy (copies per logical table)
 - tables per server-schema
 - column-presence drift across the estate
 - a concrete schema-diff matrix for one table + its merged superset

Run (from this folder):  python analyze_catalog.py
  -> charts to ../../docs/how-to-schema-consolidation/charts/
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from schema_diff import diff_table, merged_ddl

HERE = Path(__file__).parent
DATA = HERE / "data"
OUT = HERE.parent.parent / "docs" / "how-to-schema-consolidation" / "charts"
OUT.mkdir(parents=True, exist_ok=True)

# Infra layer, sibling shade of indigo. Amber = drift / anomaly flag.
INDIGO, AMBER, INK, MUTED, HAIR = "#6366F1", "#F59E0B", "#0F172A", "#64748B", "#E2E8F0"
GREY = "#CBD5E1"
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
ABBR = {
    "VARCHAR": "STR",
    "TEXT": "TXT",
    "TIMESTAMP": "TS",
    "BIGINT": "BIG",
    "DECIMAL": "DEC",
    "DOUBLE": "DBL",
    "INT": "INT",
    "DATE": "DT",
    "BOOLEAN": "BOOL",
}


def save(fig, name):
    fig.savefig(OUT / name)
    plt.close(fig)


catalog = pd.read_csv(DATA / "catalog.csv")
columns = pd.read_csv(DATA / "columns.csv")
data_dict = pd.read_csv(DATA / "data_dictionary.csv")

n_physical = len(catalog)
n_logical = catalog.logical_id.nunique()
n_documented = len(data_dict)
n_undoc = n_physical - n_documented
cov = n_documented / n_physical * 100
print(
    f"physical {n_physical:,} | logical {n_logical:,} | documented {n_documented:,} "
    f"| coverage {cov:.1f}%"
)

# 1. Coverage gap
fig, ax = plt.subplots(figsize=(8, 3.2))
ax.barh(
    ["physical tables"],
    [n_documented],
    color=INDIGO,
    label=f"documented ({n_documented:,})",
)
ax.barh(
    ["physical tables"],
    [n_undoc],
    left=[n_documented],
    color=AMBER,
    label=f"undocumented clones ({n_undoc:,})",
)
ax.set_xlim(0, n_physical)
ax.legend(frameon=False, fontsize=9, loc="lower right")
ax.set_title(
    f"The data dictionary covers {cov:.0f}% of the estate - {n_undoc:,} tables are undocumented clones"
)
ax.set_xlabel("physical tables")
ax.grid(False)
save(fig, "coverage_gap.png")

# 2. Clone redundancy: copies per logical table
copies = catalog.logical_id.value_counts()
fig, ax = plt.subplots(figsize=(8.5, 4))
vc = copies.value_counts().sort_index()
ax.bar(vc.index, vc.values, color=INDIGO)
for x, y in zip(vc.index, vc.values):
    ax.text(x, y + 4, str(y), ha="center", fontsize=8.5, color=INK)
ax.set_title(
    f"Each logical table exists on up to 9 servers - {n_physical - n_logical:,} redundant copies in all"
)
ax.set_xlabel("number of server copies of the same logical table")
ax.set_ylabel("logical tables")
save(fig, "redundancy.png")

# 3. Tables per schema
per = catalog.schema.value_counts().sort_index()
fig, ax = plt.subplots(figsize=(9, 4))
ax.bar(per.index, per.values, color=INDIGO)
for x, (s, y) in enumerate(per.items()):
    ax.text(x, y + 15, f"{y:,}", ha="center", fontsize=8.5, color=INK)
ax.set_title("Every new server cloned the whole estate - each schema holds ~950 tables")
ax.set_ylabel("physical tables")
ax.set_xlabel("server-schema")
save(fig, "tables_per_schema.png")


# 4. Drift prevalence across the estate
#    a logical table "drifts" if its column union > intersection, or a type conflict.
def col_sets(g):
    per_srv = g.groupby("schema").column_name.apply(set)
    union = set().union(*per_srv)
    inter = set(per_srv.iloc[0]).intersection(*per_srv)
    types = g.groupby("column_name").dtype.nunique()
    return pd.Series(
        {
            "union": len(union),
            "inter": len(inter),
            "singletons": sum((g.groupby("column_name").schema.nunique() == 1)),
            "type_conflict": int((types > 1).any()),
        }
    )


multi = columns[columns.logical_id.isin(copies[copies > 1].index)]
drift = multi.groupby("logical_id").apply(col_sets, include_groups=False)
drift["drifted"] = (drift.union > drift.inter) | (drift.type_conflict == 1)
pct_drift = drift.drifted.mean() * 100
pct_singleton = (drift.singletons > 0).mean() * 100
pct_typeconf = (drift.type_conflict == 1).mean() * 100
fig, ax = plt.subplots(figsize=(8.5, 4))
bars = ["column\ndrift", "has a column\non 1 server only", "dtype\nconflict"]
vals = [pct_drift, pct_singleton, pct_typeconf]
ax.bar(bars, vals, color=[AMBER, AMBER, AMBER])
for i, v in enumerate(vals):
    ax.text(
        i, v + 1, f"{v:.0f}%", ha="center", fontsize=11, fontweight="bold", color=INK
    )
ax.set_ylim(0, 100)
ax.set_title(
    "Almost every multi-server table has drifted - a blind UNION silently drops columns"
)
ax.set_ylabel("% of multi-server logical tables")
save(fig, "drift_prevalence.png")

# 5. Schema-diff matrix (HERO): pick a rich example - many servers, singletons + conflict
cand = drift[
    (drift.union >= 12) & (drift.singletons >= 1) & (drift.type_conflict == 1)
].sort_values("union", ascending=False)
example = cand.index[0] if len(cand) else copies.index[0]
d = diff_table(columns, example)
mat = d["present"].astype(int)
fig, ax = plt.subplots(figsize=(10, max(4, 0.42 * len(mat) + 1.5)))
ax.imshow(
    mat.values, aspect="auto", cmap=plt.matplotlib.colors.ListedColormap([GREY, INDIGO])
)
ax.set_xticks(range(len(d["servers"])))
ax.set_xticklabels(d["servers"], fontsize=9)
ax.set_yticks(range(len(mat)))
ylabels = ax.set_yticklabels(mat.index, fontsize=8.5, family="monospace")
for lab in ylabels:
    if lab.get_text() in d["singletons"] or lab.get_text() in d["type_conflicts"]:
        lab.set_color(AMBER)
        lab.set_fontweight("bold")
# annotate dtype abbreviations in present cells; amber text on type-conflict cells
for i, col in enumerate(mat.index):
    for j, srv in enumerate(d["servers"]):
        v = d["matrix"].loc[col, srv]
        if pd.notna(v):
            conflict = col in d["type_conflicts"]
            ax.text(
                j,
                i,
                ABBR.get(v, v),
                ha="center",
                va="center",
                fontsize=6.5,
                color=(AMBER if conflict else "white"),
            )
ax.set_title(
    f"Schema diff for {example} across {len(d['servers'])} servers - "
    f"amber = on one server only, or dtype conflict",
    fontsize=12,
)
ax.set_xlabel("server-schema")
ax.grid(False)
save(fig, "schema_diff_matrix.png")

# 6. Superset vs common for the example (what a safe merge must keep)
fig, ax = plt.subplots(figsize=(7.5, 4))
b = ax.bar(
    ["common\n(in every server)", "merged superset\n(safe union)"],
    [len(d["common"]), len(d["superset"])],
    color=[GREY, INDIGO],
)
for bar, v in zip(b, [len(d["common"]), len(d["superset"])]):
    ax.text(
        bar.get_x() + bar.get_width() / 2,
        v + 0.3,
        str(v),
        ha="center",
        fontsize=13,
        fontweight="bold",
        color=INK,
    )
ax.set_title(
    f"Merging {example}: an intersection loses {len(d['superset']) - len(d['common'])} columns - use the superset"
)
ax.set_ylabel("columns")
save(fig, "merge_superset.png")

# merged DDL artifact (printed + saved)
ddl = merged_ddl(d, table=example.lower() + "_merged")
(HERE / "example_merged.sql").write_text(ddl)
print("\n== schema diff example:", example, "==")
print(
    f"servers={len(d['servers'])} superset={len(d['superset'])} common={len(d['common'])} "
    f"singletons={d['singletons']} conflicts={list(d['type_conflicts'])}"
)
print(f"\n{len(list(OUT.glob('*.png')))} charts -> {OUT}")
