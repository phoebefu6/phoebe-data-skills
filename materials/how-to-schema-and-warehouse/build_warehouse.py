"""Everrest lineage - build STAGE 1 (lake) + STAGE 2 (warehouse) and prove it.

Executes warehouse.sql against the raw dump, writes a partitioned lake example,
validates the star schema with a pandera-style contract, runs real queries, and
renders the ERD + reconciliation charts + query-result tables for the showcase.

Run (from this folder):  python build_warehouse.py
  -> everrest.duckdb, lake/, and charts to ../../docs/how-to-schema-and-warehouse/charts/
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

HERE = Path(__file__).parent
os.chdir(HERE)  # so warehouse.sql's relative raw/ paths resolve
OUT = HERE.parent.parent / "docs" / "how-to-schema-and-warehouse" / "charts"
OUT.mkdir(parents=True, exist_ok=True)

INDIGO, AMBER, INK, MUTED, HAIR = "#4F46E5", "#F59E0B", "#0F172A", "#64748B", "#E2E8F0"
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


def save(fig, name):
    fig.savefig(OUT / name)
    plt.close(fig)


def table_png(df, name, title, highlight=None):
    """Render a small query-result DataFrame as a styled table image."""
    fig, ax = plt.subplots(
        figsize=(min(11, 1.7 * len(df.columns) + 1), 0.45 * len(df) + 1.1)
    )
    ax.axis("off")
    ax.set_title(title, loc="left", pad=12)
    tbl = ax.table(
        cellText=df.values, colLabels=df.columns, cellLoc="center", loc="center"
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9.5)
    tbl.scale(1, 1.5)
    for (r, c), cell in tbl.get_celld().items():
        cell.set_edgecolor(HAIR)
        if r == 0:
            cell.set_facecolor(INDIGO)
            cell.set_text_props(color="white", fontweight="bold")
        elif (
            highlight
            and r - 1 < len(df)
            and df.iloc[r - 1].astype(str).str.contains(highlight).any()
        ):
            cell.set_facecolor("#FEF3C7")
    save(fig, name)


# ============================================================ BUILD
con = duckdb.connect("everrest.duckdb")
con.execute(open("warehouse.sql").read())


def q(sql):
    return con.execute(sql).df()


# ---- stage 1: lake (partitioned parquet example) ----
Path("lake").mkdir(exist_ok=True)
con.execute(
    "COPY (SELECT *, month(CAST(order_ts_utc AS DATE)) AS m, "
    "year(CAST(order_ts_utc AS DATE)) AS y FROM stg_txn) "
    "TO 'lake/transactions' (FORMAT PARQUET, PARTITION_BY (y, m), OVERWRITE_OR_IGNORE)"
)
n_parts = len(list(Path("lake/transactions").rglob("*.parquet")))
print(f"lake: {n_parts} partitioned parquet files")

# ============================================================ RECONCILIATION
raw_txn = con.execute("SELECT count(*) FROM stg_txn").fetchone()[0]
fact_n = con.execute("SELECT count(*) FROM fact_orders").fetchone()[0]
orphan_p = con.execute(
    "SELECT count(*) FROM fact_orders WHERE is_orphan_product"
).fetchone()[0]
orphan_c = con.execute(
    "SELECT count(*) FROM fact_orders WHERE is_orphan_customer"
).fetchone()[0]
raw_cust_ids = con.execute(
    "SELECT count(DISTINCT customer_id) FROM stg_txn WHERE cust_signup_ts IS NOT NULL"
).fetchone()[0]
dim_cust = con.execute("SELECT count(*) FROM dim_customer").fetchone()[0]
raw_cats = con.execute("SELECT count(DISTINCT category_raw) FROM stg_txn").fetchone()[0]
clean_cats = con.execute(
    "SELECT count(DISTINCT category) FROM dim_merchant"
).fetchone()[0]
print(
    f"raw txn {raw_txn:,} -> fact {fact_n:,} | orphan product {orphan_p:,} "
    f"customer {orphan_c:,}"
)
print(
    f"customer ids {raw_cust_ids:,} -> identities {dim_cust:,} "
    f"(dedup {raw_cust_ids - dim_cust:,})"
)
print(f"category labels {raw_cats} -> {clean_cats}")

# ============================================================ CHARTS
# 1. Lineage funnel: row counts raw -> lake -> warehouse (clean, non-orphan)
clean_fact = fact_n - orphan_p
stages = [
    "raw dump\n(transactions)",
    "lake\n(partitioned)",
    "warehouse\nfact_orders",
    "modeled + clean\n(non-orphan)",
]
vals = [raw_txn, raw_txn, fact_n, clean_fact]
fig, ax = plt.subplots(figsize=(9, 4))
bars = ax.bar(stages, vals, color=[MUTED, MUTED, INDIGO, INDIGO])
for b, v in zip(bars, vals):
    ax.text(
        b.get_x() + b.get_width() / 2,
        v + 800,
        f"{v:,}",
        ha="center",
        fontsize=9,
        color=INK,
    )
ax.set_title("Row lineage: every transaction accounted for, orphans flagged not lost")
ax.set_ylabel("rows")
save(fig, "lineage_funnel.png")

# 2. Category cardinality before/after
fig, ax = plt.subplots(figsize=(7.5, 4))
b = ax.bar(
    ["raw labels\n(category_raw)", "modeled\n(dim_merchant)"],
    [raw_cats, clean_cats],
    color=[AMBER, INDIGO],
)
for bar, v in zip(b, [raw_cats, clean_cats]):
    ax.text(
        bar.get_x() + bar.get_width() / 2,
        v + 0.2,
        str(v),
        ha="center",
        fontsize=13,
        fontweight="bold",
        color=INK,
    )
ax.set_title("8 real categories arrived as 14 labels - normalized in dim_merchant")
ax.set_ylabel("distinct category values")
save(fig, "category_cardinality.png")

# 3. Orphan keys quarantined
fig, ax = plt.subplots(figsize=(8, 3.6))
labels = [
    "order_items -> product\n(no such product)",
    "orders -> customer\n(no such customer)",
]
pct = [orphan_p / fact_n * 100, orphan_c / fact_n * 100]
ax.barh(labels, pct, color=AMBER)
for i, (v, n) in enumerate(zip(pct, [orphan_p, orphan_c])):
    ax.text(
        v + 0.03, i, f"{v:.1f}%  ({n:,} rows)", va="center", fontsize=9.5, color=INK
    )
ax.set_title("Broken foreign keys quarantined by the model, not silently dropped")
ax.set_xlabel("% of fact rows flagged orphan")
save(fig, "orphan_quarantine.png")

# 4. Duplicate identity collapse
fig, ax = plt.subplots(figsize=(7.5, 4))
b = ax.bar(
    ["raw customer ids", "dim_customer\n(identities)"],
    [raw_cust_ids, dim_cust],
    color=[AMBER, INDIGO],
)
for bar, v in zip(b, [raw_cust_ids, dim_cust]):
    ax.text(
        bar.get_x() + bar.get_width() / 2,
        v + 60,
        f"{v:,}",
        ha="center",
        fontsize=12,
        fontweight="bold",
        color=INK,
    )
ax.set_title(
    f"{raw_cust_ids - dim_cust:,} duplicate identities collapsed on fingerprint"
)
ax.set_ylabel("distinct customers")
save(fig, "dup_collapse.png")

# 5. Timezone fix: latency before vs after
lat = con.execute("""
    WITH ord AS (
      SELECT order_id, min(order_ts) AS order_ts FROM fact_orders GROUP BY order_id
    ),
    j AS (
      SELECT p.paid_at, c.paid_ts_utc, ord.order_ts
      FROM clean_payments c
      JOIN stg_payments p ON p.pmt_ref = c.pmt_ref
      JOIN ord ON ord.order_id = c.order_id
    )
    SELECT
      date_diff('minute', order_ts, paid_at) / 60.0     AS before_h,
      date_diff('minute', order_ts, paid_ts_utc) / 60.0 AS after_h
    FROM j
    """).df()
fig, ax = plt.subplots(figsize=(9, 4))
ax.hist(
    lat.before_h.clip(-10, 5),
    bins=60,
    color=AMBER,
    alpha=0.85,
    label="before (raw paid_at)",
)
ax.hist(
    lat.after_h.clip(-10, 5),
    bins=60,
    color=INDIGO,
    alpha=0.7,
    label="after TZ fix (paid_ts_utc)",
)
ax.axvline(0, color=INK, lw=1)
ax.legend(frameon=False, fontsize=9)
ax.set_title("Timezone fix: PH payments no longer land before their order")
ax.set_xlabel("payment latency (hours)")
ax.set_ylabel("payments")
save(fig, "timezone_fix.png")

# 6. Fabrication: reported payments vs modeled order value, per merchant
fab = con.execute("""
    WITH order_net AS (
      SELECT order_id, merchant_id, sum(net_amount) AS net
      FROM fact_orders GROUP BY 1, 2
    ),
    j AS (
      SELECT o.merchant_id,
             sum(p.amount_reported) AS reported,
             sum(o.net)             AS modeled
      FROM order_net o JOIN clean_payments p USING (order_id)
      GROUP BY 1
    )
    SELECT merchant_id, reported, modeled, abs(reported - modeled) AS gap
    FROM j ORDER BY gap DESC LIMIT 8
    """).df()
fig, ax = plt.subplots(figsize=(9, 4))
colors = [AMBER if m == "M0333" else INDIGO for m in fab.merchant_id]
ax.bar(fab.merchant_id, fab.gap, color=colors)
ax.set_title("M0333 reported payments diverge from modeled order value - fabrication")
ax.set_ylabel("|reported - modeled| ($)")
ax.set_xlabel("merchant")
save(fig, "fabrication_gap.png")

# ============================================================ QUERY -> RESULT (before/after)
raw_cat = q(
    "SELECT category_raw AS category, round(sum(qty*unit_price*(1-discount))) AS revenue "
    "FROM stg_txn GROUP BY 1 ORDER BY revenue DESC LIMIT 14"
)
table_png(
    raw_cat,
    "query_raw_category.png",
    "BEFORE - GROUP BY on the raw label: 14 split, mislabeled buckets",
    highlight="Grocary",
)

clean_cat = q(
    "SELECT dm.category, round(sum(f.net_amount)) AS revenue "
    "FROM fact_orders f JOIN dim_merchant dm USING (merchant_id) "
    "WHERE NOT f.is_orphan_product AND f.status <> 'cancelled' "
    "GROUP BY 1 ORDER BY revenue DESC"
)
table_png(
    clean_cat,
    "query_clean_category.png",
    "AFTER - one clean join on the star schema: 8 whole categories",
)

# a proper star-join business query
topm = q(
    "SELECT dm.merchant_id, dm.category, dm.tier, "
    "round(sum(f.net_amount)) AS revenue "
    "FROM fact_orders f JOIN dim_merchant dm USING (merchant_id) "
    "WHERE NOT f.is_orphan_product AND f.status <> 'cancelled' "
    "GROUP BY 1,2,3 ORDER BY revenue DESC LIMIT 6"
)
table_png(
    topm,
    "query_top_merchants.png",
    "Star-schema join: top merchants by revenue (fact_orders x dim_merchant)",
    highlight="M0007",
)

# ============================================================ CONTRACT VALIDATION
import pandera.pandas as pa

fact = con.execute("SELECT * FROM fact_orders").df()
schema = pa.DataFrameSchema(
    {
        "txn_id": pa.Column(str, unique=True),
        "order_id": pa.Column(str),
        "qty": pa.Column(int, pa.Check.ge(1)),
        "net_amount": pa.Column(float, pa.Check.ge(0)),
        "is_orphan_product": pa.Column(bool),
        "is_orphan_customer": pa.Column(bool),
        "status": pa.Column(
            str, pa.Check.isin(["delivered", "shipped", "paid", "cancelled"])
        ),
    }
)
try:
    schema.validate(fact, lazy=True)
    contract_ok = True
    print("contract: PASS - fact_orders satisfies the data contract")
except pa.errors.SchemaErrors as e:
    contract_ok = False
    print("contract: FAIL\n", e.failure_cases.head())

# non-orphan FK integrity: every non-orphan product_id exists in dim_product
fk_ok = con.execute(
    "SELECT count(*) FROM fact_orders f WHERE NOT is_orphan_product "
    "AND NOT EXISTS (SELECT 1 FROM dim_product d WHERE d.product_id=f.product_id)"
).fetchone()[0]
print(f"referential integrity (non-orphan product FK violations): {fk_ok}")


# ============================================================ ERD
def cols(table):
    return con.execute(f"PRAGMA table_info('{table}')").df().name.tolist()


def erd_box(ax, x, y, w, h, title, fields, is_fact=False):
    fc = INDIGO if is_fact else "#EEF2FF"
    tc = "white" if is_fact else INK
    ax.add_patch(
        mpatches.FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.02,rounding_size=0.06",
            fc=fc,
            ec=INDIGO,
            lw=1.6,
            zorder=3,
        )
    )
    ax.text(
        x + w / 2,
        y + h - 0.28,
        title,
        ha="center",
        va="top",
        fontsize=10.5,
        fontweight="bold",
        color=tc,
        zorder=4,
    )
    for i, f in enumerate(fields):
        ax.text(
            x + 0.12,
            y + h - 0.62 - i * 0.26,
            f,
            ha="left",
            va="top",
            fontsize=7.6,
            color=tc if is_fact else MUTED,
            zorder=4,
            family="monospace",
        )


fig, ax = plt.subplots(figsize=(11, 7.5))
ax.set_xlim(0, 12)
ax.set_ylim(0, 9)
ax.axis("off")
ax.set_title(
    "Everrest star schema - fact_orders + 4 conformed dimensions",
    fontsize=13,
    fontweight="bold",
    color=INK,
    loc="center",
)
fact_fields = [c for c in cols("fact_orders")][:12]
erd_box(ax, 4.4, 3.4, 3.2, 3.0, "fact_orders", fact_fields, is_fact=True)
dims = [
    ("dim_merchant", cols("dim_merchant"), 0.4, 6.2),
    ("dim_customer", cols("dim_customer"), 8.4, 6.2),
    ("dim_product", cols("dim_product"), 0.4, 1.0),
    ("dim_date", cols("dim_date"), 8.4, 1.0),
]
centers = {}
for name, c, x, y in dims:
    erd_box(ax, x, y, 3.2, 2.0, name, c[:6])
    centers[name] = (x + 1.6, y + 1.0)
fc_center = (6.0, 4.9)
for name, (cx, cy) in centers.items():
    ax.plot(
        [fc_center[0], cx],
        [fc_center[1], cy],
        color=INDIGO,
        lw=1.1,
        zorder=1,
        alpha=0.6,
    )
save(fig, "schema_erd.png")

print(f"\ncharts -> {OUT}")
print(f"{len(list(OUT.glob('*.png')))} PNGs")
con.close()
