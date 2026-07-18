---
name: how-to-eda
description: Run a decision-first exploratory data analysis (EDA) with Claude + Python on any schema. Use when handed a data schema or new dataset and asked to "explore the data", "run EDA", "profile this", "what's in this data", "can we trust this data", or before building any dashboard/model on unfamiliar tables. Walks the 6-step pipeline - input, sample data (if no real data yet), objective, find-skills, code with real executed charts, expert review - and outputs findings ranked by dollar impact.
---

# how-to-EDA-using-claude-python

Decision-first EDA: the output is a ranked list of findings an executive can act on,
with charts as evidence - not a wall of describe() output.

Showcase walkthrough (Everrest retail case, real executed charts):
https://github.com/phoebefu6/phoebe-data-skills - `docs/how-to-eda-using-claude-python/`

## The 6 steps

### 1. Input
Collect the schema (tables, columns, types, one-line descriptions) and business
context (industry, business model, what the org cares about this quarter).
If given real data, also note grain and row counts per table. Never proceed on
column names alone - ask what the business would pay to know.

### 2. Sample data (only when real data isn't available yet)
Write a seeded generator (`numpy.random.default_rng(<seed>)`) at realistic scale.
Plant quirks on purpose - missing-not-at-random, outlier entities, duplicates,
seasonality, one suspicious segment - and document each in the docstring. EDA that
finds nothing teaches nothing, and the planted list becomes your recall test.
With real data, skip generation; the quirks are already in there.

### 3. Objective
Frame ONE decision question ("what should <team> act on this quarter, and what in
this data can't be trusted yet?"), then 3-5 sub-questions. Every chart must serve
a sub-question; anything else is decoration.

### 4. Find-skills
List the tools/skills that assist this objective before writing code:
ydata-profiling (10-minute head start), Great Expectations (turn findings into
permanent gates), dataviz discipline (form follows relationship), any in-house
analysis playbooks. Reuse beats rebuilding.

### 5. Code + charts
One script, sectioned to mirror the sub-questions, in this order:
1. **Data-quality gate FIRST**: duplicates, phantom rows (e.g. cancelled orders in
   revenue), referential integrity, missingness overall AND by segment (that's how
   missing-not-at-random shows up). Quantify each issue in $.
2. **Business questions on the CLEAN data**: concentration (pareto), distributions
   (log scale when skewed - means lie), time patterns (seasonal decomposition,
   day-of-week x hour), cohorts/retention, segment anomalies.
Rules: fixed seed stated in output; every chart titled with its FINDING, not its
technique ("Top 20 merchants = 68% of revenue", never "Bar chart of revenue");
name anomalous entities on the chart; 300 DPI PNGs; aim for 10+ chart types when
the data supports them; kill any chart with no action attached.

### 6. Expert review
Convene a panel of 4-6 senior reviewer agents, each with 10+ years in data,
data insights, and business. Have them review the actual code + outputs through
these lenses, apply the fixes, and re-run:
- **Code & pipeline integrity**: dedup before aggregates? leakage of phantom rows? vectorized?
- **Methodology & rigor**: DQ gate separated from analysis? reproducible (seed, env documented)? missingness checked by segment, not just overall?
- **Decision framing**: does every chart answer a sub-question? technique-titled charts renamed or cut?
- **Business impact**: is every finding quantified in $ and ranked? would an exec know what to do next?
- **QA & reproducibility**: does a clean re-run reproduce byte-identical output and recover every planted quirk?
Keep the before/after - review that changes nothing is theater.

## Output format
`findings.md`: findings ranked by $ impact, each 2-3 sentences: what, evidence
(which chart), recommended action. Charts in a `charts/` folder. Script(s) runnable
top-to-bottom from a fresh shell.

## Baseline script (start here, then tune)

This skill ships a runnable baseline in `baseline/` - the real code behind the
Everrest showcase. Read it as the starting point, then tune it to the user's
schema and question:

- `${CLAUDE_SKILL_DIR}/baseline/eda_everrest_v2.py` - the decision-first EDA (DQ gate + $-ranked findings + charts)
- `${CLAUDE_SKILL_DIR}/baseline/generate_everrest.py` - seeded sample data (skip when real data exists)

Run it in a Python env with pandas + matplotlib (plus any extras noted). Point it
at the user's data, then change what the use case needs - new columns, a different
decision question, their industry. The showcase page walks the full example.
