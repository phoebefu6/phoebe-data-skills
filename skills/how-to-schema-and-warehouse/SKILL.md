---
name: how-to-schema-and-warehouse
description: Turn a raw operational data dump into a queryable star-schema warehouse with a data contract, using DuckDB + pandera. Use when handed raw exports from one or more source systems and asked to "design a schema", "build a warehouse", "model this data", "set up a data lake / warehouse", "create a star schema", "reconcile these sources", or before any analytics/BI is built on unmodeled data. Walks the 6-step pipeline - input, sample data, objective, find-skills, build (ERD + DDL + contract + real queries), expert review - and outputs a genuinely queryable warehouse, not just a diagram.
---

# how-to-schema-and-warehouse

Infrastructure-layer skill (the base of the phoebe-data-skills 4-layer roadmap).
Trust-first: the output is a warehouse someone can actually query plus a contract
that keeps it trustworthy - never a pretty ERD of already-clean data.

Showcase walkthrough (Everrest retail case, real DuckDB build):
https://github.com/phoebefu6/phoebe-data-skills - `docs/how-to-schema-and-warehouse/`

## The lineage this skill produces
`raw dump (messy sources) -> lake (partitioned) -> warehouse (star schema) -> marts`.
Defects live in the raw layer; the warehouse transform is where they get resolved.

## The 6 steps

### 1. Input
Collect the raw sources as-is: every export, its key format, its grain, its
defects. Note where keys should join across systems. Do not assume anything is
clean - a real platform is handed exports, not tables.

### 2. Sample data (only when real data isn't available yet)
Write a seeded generator producing the raw dump from multiple "source systems"
with ingestion-flavored defects planted on purpose: orphan foreign keys,
heterogeneous keys across systems, dirty categorical labels, timezone/timestamp
bugs, fabricated amounts, duplicate identities. Document each in the docstring.
With real data, skip - the defects are already there.

### 3. Objective
Frame the trust question: "can we turn this dump into a warehouse the company can
query and trust, and what breaks if we skip modeling?" 3-5 sub-questions covering
keys resolving, sources reconciling, entities cleaning, one clean query working,
and enforceability.

### 4. Find-skills
Assemble the modeling toolbox: DuckDB (query files directly, build the star
in-process), pandera (integrity assertions as code), Great Expectations (promote
to CI gate), DataHub/OpenMetadata (catalog + lineage), Kimball star-schema
pattern. Reuse beats rebuilding.

### 5. Build (infra track)
One SQL file (`warehouse.sql`) does the transform: stage each raw source,
reconcile keys, normalize labels, dedupe identities, fix timestamps, then build
one fact at a stated grain + conformed dimensions. Orphan keys are FLAGGED on the
fact, never silently dropped. Produce four artifacts:
1. **ERD** rendered from the real schema (matplotlib/graphviz).
2. **DDL** - `warehouse.sql`, runnable in DuckDB from the raw dump.
3. **data_contract.yaml** - pandera/GE assertions (types, not-null, FK-in-dim,
   accepted values, no-negative-latency); run it and show PASS.
4. **Real query -> result pairs** - the same business question before (raw dump,
   split/wrong) and after (star schema, one clean join), plus row-count
   reconciliation across every lineage stage.
Honesty gate: the warehouse must be genuinely queryable - show real executed SQL
and the real rows it returned, never an ERD alone. Row counts must reconcile.

### 6. Expert review
Panel of 4-6 anonymous senior reviewers - include a **data architect** and a
**data-contract/governance** reviewer alongside engineer/methodology/business.
They review the actual SQL + outputs, give concrete fixes; apply them and re-run.
Keep the before/after (naive raw query -> modeled warehouse).

## Output format
A runnable `warehouse.sql` + `everrest.duckdb`, `data_contract.yaml`, the ERD, and
query->result evidence. Reconciliation charts in `charts/`. Everything runs
top-to-bottom from a fresh shell with a fixed seed.
