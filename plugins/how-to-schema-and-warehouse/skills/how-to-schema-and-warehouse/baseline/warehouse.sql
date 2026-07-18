-- Everrest lineage - STAGE 2: raw dump -> queryable star schema (DuckDB).
--
-- Run from this folder:  duckdb everrest.duckdb < warehouse.sql
-- Reads ./raw/*, writes conformed dims + fact_orders. The cleaning IS the point:
-- every planted quirk from the raw dump is resolved here.
--
-- Grain of fact_orders: one order line item (one row per raw transaction).

-- ============================================================ STAGING
CREATE OR REPLACE TABLE stg_txn AS
    SELECT * FROM read_csv_auto('raw/raw_transactions.csv', header=true);
CREATE OR REPLACE TABLE stg_products AS
    SELECT * FROM read_csv_auto('raw/raw_products_export.csv', header=true);
CREATE OR REPLACE TABLE stg_merchants AS
    SELECT * FROM read_json_auto('raw/raw_merchants_extract.json');
CREATE OR REPLACE TABLE stg_payments AS
    SELECT * FROM read_csv_auto('raw/raw_payments_export.csv', header=true);

-- Reusable category normalizer: 14 dirty labels -> 8 canonical categories.
CREATE OR REPLACE MACRO clean_category(c) AS (
    CASE lower(trim(c))
        WHEN 'electronics'      THEN 'Electronics'
        WHEN 'beauty'           THEN 'Beauty'
        WHEN 'grocery'          THEN 'Grocery'
        WHEN 'grocary'          THEN 'Grocery'
        WHEN 'apparel'          THEN 'Apparel'
        WHEN 'home & living'    THEN 'Home & Living'
        WHEN 'toys & kids'      THEN 'Toys & Kids'
        WHEN 'toys and kids'    THEN 'Toys & Kids'
        WHEN 'sports & outdoor' THEN 'Sports & Outdoor'
        WHEN 'pet supplies'     THEN 'Pet Supplies'
        ELSE trim(c)
    END
);

-- ============================================================ DIM_MERCHANT
-- Quirk 3 (heterogeneous keys): reconcile 'MER-0001' -> 'M0001' via legacy_id.
-- Quirk 2 (dirty categoricals): normalize 14 labels -> 8.
CREATE OR REPLACE TABLE dim_merchant AS
SELECT
    row_number() OVER (ORDER BY legacy_id)      AS merchant_sk,
    legacy_id                                   AS merchant_id,
    merchant_key                                AS source_key,
    clean_category(category)                    AS category,
    tier,
    CAST(onboarded AS DATE)                     AS onboarded_at
FROM stg_merchants;

-- ============================================================ DIM_CUSTOMER
-- Quirk 6 (duplicate identities): collapse ids sharing an identical
-- (signup_ts, channel, region) fingerprint to one canonical customer.
-- Orphan customers (null attributes) are excluded from the dim.
CREATE OR REPLACE TABLE cust_xwalk AS
WITH cust AS (
    SELECT DISTINCT customer_id,
           cust_signup_ts AS signup_ts, cust_channel AS channel, cust_region AS region
    FROM stg_txn
    WHERE cust_signup_ts IS NOT NULL
)
SELECT customer_id AS raw_customer_id,
       min(customer_id) OVER (PARTITION BY signup_ts, channel, region) AS customer_id,
       signup_ts, channel, region
FROM cust;

CREATE OR REPLACE TABLE dim_customer AS
SELECT
    row_number() OVER (ORDER BY customer_id)    AS customer_sk,
    customer_id,
    signup_ts,
    channel,
    region,
    count(*)                                    AS merged_source_ids
FROM cust_xwalk
GROUP BY customer_id, signup_ts, channel, region;

-- ============================================================ DIM_PRODUCT
CREATE OR REPLACE TABLE dim_product AS
SELECT
    row_number() OVER (ORDER BY product_id)     AS product_sk,
    product_id,
    merchant_id,
    catalog_price
FROM stg_products;

-- ============================================================ DIM_DATE
CREATE OR REPLACE TABLE dim_date AS
SELECT
    CAST(d AS DATE)                             AS date_key,
    year(d)                                     AS year,
    month(d)                                    AS month,
    monthname(d)                                AS month_name,
    dayofweek(d)                                AS dow,
    CASE WHEN dayofweek(d) IN (0, 6) THEN TRUE ELSE FALSE END AS is_weekend,
    CASE WHEN month(d) = 11 THEN TRUE ELSE FALSE END         AS is_november
FROM generate_series(DATE '2025-07-01', DATE '2026-06-30', INTERVAL 1 DAY) AS t(d);

-- ============================================================ CLEAN PAYMENTS
-- Quirk 4 (timezone): PH payments logged in local time -> shift +8h back to UTC.
CREATE OR REPLACE TABLE clean_payments AS
SELECT
    p.pmt_ref,
    p.order_id,
    p.method,
    p.amount_reported,
    CASE WHEN c.region = 'PH'
         THEN p.paid_at + INTERVAL 8 HOUR
         ELSE p.paid_at END                     AS paid_ts_utc
FROM stg_payments p
LEFT JOIN (SELECT DISTINCT order_id, customer_id FROM stg_txn) o USING (order_id)
LEFT JOIN cust_xwalk x ON o.customer_id = x.raw_customer_id
LEFT JOIN dim_customer c ON x.customer_id = c.customer_id;

-- ============================================================ FACT_ORDERS
-- Grain: one order line. Orphan keys are flagged, not silently dropped.
CREATE OR REPLACE TABLE fact_orders AS
SELECT
    t.txn_id,
    t.order_id,
    CAST(t.order_ts_utc AS TIMESTAMP)           AS order_ts,
    CAST(t.order_ts_utc AS DATE)                AS date_key,
    lower(trim(t.status))                       AS status,        -- fix mixed casing
    x.customer_id                               AS customer_id,   -- canonical (dedup'd)
    dm.merchant_id,
    dp.product_id,
    t.qty,
    t.unit_price,
    dp.catalog_price,
    round(t.unit_price - dp.catalog_price, 2)   AS price_gap,     -- stale-price signal
    t.discount,
    round(t.qty * t.unit_price * (1 - t.discount), 2) AS net_amount,
    (dp.product_id IS NULL)                     AS is_orphan_product,
    (x.customer_id IS NULL)                     AS is_orphan_customer
FROM stg_txn t
LEFT JOIN cust_xwalk x ON t.customer_id = x.raw_customer_id
LEFT JOIN dim_merchant dm ON t.merchant_id = dm.merchant_id
LEFT JOIN dim_product dp ON t.product_id = dp.product_id;
