---
name: how-to-metric-to-scorecard
description: Turn raw marts into a board-ready executive scorecard - define metrics explicitly, validate each against the naive version an analyst ships by accident, then generate a self-contained HTML scorecard where every number is computed, not hand-typed. Use when asked to "build a scorecard", "executive/board dashboard", "KPI report", "define our metrics", "revenue dashboard", "what do we put in front of the board", "metric definitions", or when a stakeholder wants numbers they can trust and audit. Walks the 6-step pipeline - input, sample data, objective, find-skills, build (metric definitions + validation + HTML scorecard), expert review - and outputs an auditable scorecard, not a pile of aggregates.
---

# how-to-metric-to-scorecard

Data-Analytics-layer skill (layer 2 of the phoebe-data-skills 4-layer roadmap).
The job is not "make a dashboard" - it is to turn a number into a *decision the
board can trust*. Every metric ships with its definition and a validation that
shows what it would say if you got it wrong.

Showcase walkthrough (Everrest retail case, real computed scorecard):
https://github.com/phoebefu6/phoebe-data-skills - `docs/how-to-metric-to-scorecard/`

## Where this sits in the lineage
`raw dump -> lake -> warehouse -> marts` **-> executive scorecard**. This skill
reads the clean marts (the output of `how-to-schema-and-warehouse`) and turns
them into the artifact an executive actually looks at.

## The one rule that separates it from every dashboard tutorial
**A metric is a decision made numeric, not just an aggregate.** So every tile
carries three things: the number, its definition (formula, grain, filter), and a
validation - the naive version and how far off it is. If you cannot state the
definition and defend it against the naive version, it is not board-ready.

## The 6 steps

### 1. Input
The marts (or the user's tables): orders, order_items, returns, merchants,
customers. Note the grain of each and the status field - it decides what counts.

### 2. Sample data (only when real data isn't available yet)
Reuse the seeded Everrest marts (seed 42). For a client, skip - use their marts.

### 3. Objective
Frame the board question: "what eight numbers does the board need this quarter,
and can we defend each one?" Not "build a dashboard." 6-10 metrics, each tied to
a decision (revenue, growth, unit economics, marketplace health, risk).

### 4. Find-skills
pandas for the compute, a period/grain discipline, one hardened HTML template
(deploy-html), tabular-nums typography, RAG + period-over-period conventions.

### 5. Build (scorecard track)
1. Define 6-10 metrics **explicitly** - formula, grain, filter, owner - in code,
   not prose. A metric definition is a function, not a sentence.
2. **Validate each**: compute the naive version too (no status filter, outlier
   left in, wrong denominator) and record how far off it is. Ship the delta.
3. Generate a **self-contained HTML scorecard** from the computed values - KPI
   tiles with tabular-nums heroes, RAG status, period-over-period deltas, a
   trend sparkline, one narrative headline. **Never hand-type a number** - the
   python writes every value into the HTML.
4. Write all values to `metrics.json` so the scorecard is reproducible and
   auditable.
Honesty gate: every figure reconciles to the marts and is produced by the
committed script; the definitions are on the card so a reader can audit each one.

### 6. Expert review
Panel of 4-6 anonymous senior reviewers - include a **BI / analytics-engineering**
reviewer and a **commercial / board** reviewer alongside methodology and
engineering. They check the metrics are the ones a board asks for and that each
survives its validation; apply the fixes and re-generate.

## Output format
A runnable `build_scorecard.py` + `metrics.json`, `everrest_scorecard.html` (the
self-contained artifact), and the supporting PNGs. Everything runs top-to-bottom
from a fresh shell; the scorecard opens in any browser with no dependencies.

## Baseline script (start here, then tune)

This skill ships a runnable baseline in `baseline/` - the real code behind the
Everrest showcase. Read it, then tune it to the user's marts and the metrics
their board actually asks for:

- `${CLAUDE_SKILL_DIR}/baseline/build_scorecard.py` - reads marts, defines +
  validates every metric, renders the charts, and generates the self-contained
  HTML scorecard (all numbers injected from computed values).

Run it in a Python env with pandas + matplotlib. Point `MARTS` at the user's
data, change the metric set and the take-rate assumption, then regenerate. The
showcase page walks the full example.
