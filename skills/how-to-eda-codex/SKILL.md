---
name: how-to-eda-codex
description: Run a trust-first exploratory data analysis (EDA) with Codex + Python on any schema, assembling an open-source profiling / integrity / forensic toolbox before writing code. Use when handed a new dataset from an unproven pipeline and asked to "can we trust this data", "profile this", "run EDA", "check data quality", "find integrity issues", or before building any dashboard/model on unfamiliar tables. Walks the same 6-step pipeline as how-to-eda (the Claude edition) but leads with referential integrity, entity resolution, and forensic checks - and outputs findings ranked by dollar and trust impact.
---

# how-to-EDA-using-codex-python

Trust-first EDA: the output is a ranked list of integrity and business findings an
executive can act on, with charts as evidence - not a wall of describe() output.
Sibling of `how-to-eda` (Claude edition): same spine, a toolbox that Codex
assembles from OpenAI/GitHub agent skills plus open-source data libraries, and a
sharper focus on the defects that hide across joins.

Showcase walkthrough (Everrest retail case, real executed charts):
https://github.com/phoebefu6/phoebe-data-skills - `docs/how-to-eda-using-codex-python/`

## The 6 steps

### 1. Input
Collect the schema (tables, columns, types, one-line descriptions) and business
context. When the data comes from a fresh or unproven pipeline, the objective
shifts from "what's growing" to "can this be trusted yet". Note grain and row
counts. Never trust a foreign key until it has been proven to resolve.

### 2. Sample data (only when real data isn't available yet)
Write a seeded generator (`numpy.random.default_rng(<seed>)`) at realistic scale.
Plant integrity-flavored quirks on purpose - orphan foreign keys, stale price
snapshots, timezone/timestamp bugs, dirty categorical labels, fabricated
(round-number / Benford-breaking) amounts, duplicate identities - and document
each in the docstring. With real data, skip generation; the defects are already
in there.

### 3. Objective
Frame ONE trust question ("can this data be trusted for this quarter's decisions,
and which defect would embarrass the team if shipped?"), then 3-5 sub-questions
covering keys, values, entities, and the cleaned business read. Every chart must
serve one; anything else is decoration.

### 4. Find-skills - assemble the toolbox
Before writing code, activate agent skills to find the right tools, then pull the
libraries that serve this objective:
- **Agent layer**: OpenAI Codex CLI (authoring), superpowers / `find-skills`
  (route to specialists), grill-me (sharpen the objective).
- **Profiling**: sweetviz or ydata-profiling (one-shot report - the 10-minute
  head start), missingno (missingness matrix).
- **Validation**: pandera (schema + referential-integrity assertions as code),
  Great Expectations (promote findings to permanent CI gates).
- **Forensic**: scipy + Benford's-law first-digit test, round-number heaping.
- **Discipline**: dataviz (one anomaly color across every chart),
  schema-to-insights (DQ gate first, rank by $ / trust).
Reuse beats rebuilding - the point of a shelf is that the next analysis starts here.

### 5. Code + charts
One script, sectioned to mirror the sub-questions, in this order:
1. **Profiling head start**: run the profile report first; read off the free
   signals (missing-on-join, distinct-count blowups, negative-tailed gaps).
2. **Data-quality &amp; integrity gate**: referential integrity (orphan FKs),
   duplicate identities, dirty-label normalization, timestamp sanity (no negative
   latency), value reconciliation (payments vs line items), Benford. Quantify
   each in $ or trust terms and clean before analysis.
3. **Business questions on the CLEAN data**: concentration (pareto), distributions
   (log scale when skewed), seasonal decomposition, day-of-week x hour, cohorts,
   category small-multiples (on normalized labels), geography.
Rules: fixed seed stated in output; every chart titled with its FINDING, not its
technique; one consistent anomaly color (amber) means "this is the problem";
name anomalous entities on the chart; 300 DPI PNGs; aim for 16+ visuals when the
data supports them; kill any chart with no action attached.

### 6. Expert review
Convene a panel of 4-6 senior reviewer agents, each with 10+ years in data, data
insights, and business. Review the actual code + outputs through these lenses,
apply the fixes, and re-run:
- **Pipeline &amp; integrity**: are foreign keys checked before joining? orphans quantified?
- **Methodology**: are dirty labels normalized before rollups? DQ gate separated from analysis?
- **Decision framing**: does every chart answer a sub-question? technique titles cut?
- **Business impact**: is every finding quantified and ranked? would the board be misled without it?
- **QA &amp; reproducibility**: does a clean re-run reproduce output and recover every planted quirk?
Keep the before/after - review that changes nothing is theater.

## Output format
`findings.md`: findings ranked by $ / trust impact, each 2-3 sentences: what,
evidence (which chart), recommended action. Charts in a `charts/` folder. Script(s)
runnable top-to-bottom from a fresh shell.
