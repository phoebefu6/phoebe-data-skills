CREATE TABLE l0646_merged (
    server_source VARCHAR,   -- lineage: which server this row came from
    carrier DECIMAL,
    created_at TIMESTAMP,
    currency BOOLEAN,
    discount_pct BOOLEAN,
    external_ref TIMESTAMP,
    id BIGINT,
    is_deleted VARCHAR,
    notes VARCHAR,
    priority VARCHAR,
    risk_score VARCHAR,   -- TYPE CONFLICT DATE/TIMESTAMP
    segment TIMESTAMP,
    source_system VARCHAR,
    srv03_ext_3 VARCHAR,   -- only 1 server
    srv04_ext_1 VARCHAR,   -- only 1 server
    srv05_ext_1 VARCHAR,   -- only 1 server
    srv06_ext_1 VARCHAR,   -- only 1 server
    srv09_ext_3 VARCHAR,   -- only 1 server
    status VARCHAR,
    updated_at TIMESTAMP,
    warehouse_id VARCHAR,   -- TYPE CONFLICT TEXT/VARCHAR
);