---
name: how-to-schema-consolidation
description: Audit a sprawling multi-server data estate (many cloned schemas that have drifted) and safely consolidate the copies of a table into one, using a column-level schema diff. Use when handed many servers/schemas that each cloned the same tables, or asked to "consolidate schemas", "merge duplicate tables", "compare schemas across servers", "schema diff", "which columns differ across environments", "dedupe tables", "measure data dictionary coverage", or before merging any table that exists in more than one database. Walks the 6-step pipeline - input, sample data, objective, find-skills, build (coverage + redundancy + drift audit, schema-diff matrix, merged superset DDL), expert review - and never merges on the intersection.
---

# how-to-schema-consolidation

Infrastructure-layer skill (sibling to how-to-schema-and-warehouse). The realistic
enterprise problem: one server per region/workload, each cloning the whole schema,
copies drifting over time, and a data dictionary that only ever covered the logical
tables. Output is an honest audit of the sprawl plus a safe, column-complete merge -
never a blind UNION that drops server-unique columns.

Showcase walkthrough (Everrest estate: 9 servers, 8,600 tables):
https://github.com/phoebefu6/phoebe-data-skills - `docs/how-to-schema-consolidation/`

## The 6 steps

### 1. Input
Collect a catalog of every physical table across every server/schema, a column
inventory (schema, table, column, dtype), and whatever data dictionary exists.
Note the mapping from physical copy to logical table.

### 2. Sample data (only when real data isn't available yet)
Simulate the estate: N logical tables replicated across S servers with partial
replication, drifted per copy (optional columns present/absent, server-unique
singleton columns, occasional plausible dtype drift), and a dictionary that
documents only the logical set. Document the planted realities. With real data,
skip - export the catalog from information_schema across servers.

### 3. Objective
Frame the consolidation decision: "merge every table's copies into one truth
without losing a column that lives on only one server." Sub-questions on coverage,
redundancy, per-table column drift, singletons, and dtype conflicts.

### 4. Find-skills
Reuse catalog/lineage tooling (OpenMetadata, DataHub) to close the doc gap; DuckDB
for fast set operations over the column inventory; Great Expectations to lock the
merged schema as a contract. Write the one missing piece: a schema-diff engine.

### 5. Build (infra track)
1. **Audit the sprawl**: documentation coverage (documented / physical),
   redundancy (copies per logical table, retireable clones), tables per server.
2. **Measure drift** across the estate: union vs intersection of columns per
   logical table, % with singleton columns, % with dtype conflicts.
3. **Diff one table** across all servers with the reusable engine: a column x
   server presence matrix, singletons and type conflicts flagged (amber).
4. **Merge safely**: emit a superset CREATE TABLE - union of all columns, a
   server_source lineage column, each singleton tagged, dtype conflicts widened.
   NEVER merge on the intersection.
Honesty gate: the diff must be exact and reproducible (fixed seed / re-runnable);
the merged DDL must lose zero columns; show the intersection-vs-superset gap.

### 6. Expert review
Panel of 4-6 anonymous senior reviewers - include a platform/migration architect
and a governance lead. They review the merge approach and outputs; apply fixes and
re-run. Keep the before/after (intersection merge -> superset merge).

## Output format
`schema_diff.py` (reusable: `diff_table`, `merged_ddl`), an estate audit with
charts, and a merged superset `.sql` per consolidated table. Runs top-to-bottom
from a fresh shell with a fixed seed.
