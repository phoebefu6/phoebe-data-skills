---
name: how-to-data-quality
description: Put a data-quality gate on a warehouse load - map every defect to one of the six DQ dimensions (completeness, validity, consistency, timeliness, uniqueness, accuracy), run a real FAIL -> fix -> PASS cycle with a quarantine ledger that reconciles every row, and generate a self-contained executive DQ scorecard where every number is computed. Use when asked to "check data quality", "validate this load", "build DQ checks", "data quality scorecard", "should we trust this data", "set up a quality gate", "quarantine bad rows", or when a pipeline needs defects caught at ingestion instead of in a board meeting. Walks the 6-step pipeline - input, sample data, objective, find-skills, build (gate + fixes + scorecard), expert review.
---

# how-to-data-quality

Data-Analytics-layer skill (layer 2 of the phoebe-data-skills 4-layer roadmap).
The job is not "run some checks" - it is a **gate with a verdict**: does the
load ship, or is it blocked, and where did every row go?

Showcase walkthrough (Everrest retail case, real FAIL -> PASS run):
https://github.com/phoebefu6/phoebe-data-skills - `docs/how-to-data-quality/`

## Where this sits in the lineage
**raw dump -> [THIS GATE] -> warehouse** -> marts -> scorecard/agent. Quality
problems are ingestion problems; catch them where they enter, with a ledger,
not downstream where they surface as a wrong board number.

## The three rules that separate it from every DQ tutorial

1. **A gate, not a report.** Any BLOCKER failure blocks the load, whatever the
   average score says. A DQ score that averages its way past a blocker is
   decoration.
2. **Every row is accounted for.** rows_in = rows_loaded + rows_quarantined
   (+ merged). Quarantine with reasons; never silently drop.
3. **Route fabrication, never repair it.** A suspicious amount is evidence for
   an investigation, not a formatting defect. Hold it out of finance rollups
   and preserve it untouched. A pipeline that "corrects" fabricated data is
   lying twice.

## The six dimensions, as checks

| Dimension | Check pattern | Everrest example |
|---|---|---|
| completeness | required attributes present | orphan customer refs surface as nulls |
| validity | accepted values / types / ranges | 14 labels arrive for 8 categories |
| consistency | referential + cross-system conformity | product FKs; MER-0001 vs M0001 keys |
| timeliness | event order, freshness | payments 8h before their orders (tz bug) |
| uniqueness | one entity, one id | ~800 customers under two ids |
| accuracy | plausibility screens | one merchant 100% round-hundred amounts |

## The 6 steps

### 1. Input
The raw files feeding a load (or the user's tables) + the target schema. Note
which columns are keys, which are event timestamps, which fields finance reads.

### 2. Sample data (only when real data isn't available yet)
Reuse the seeded Everrest raw dump (seed 42, 6 planted defects with known
ground truth). For a client, skip - use their raw extracts.

### 3. Objective
"Does Monday's load ship?" - 3-5 sub-questions: what blocks vs warns, what gets
quarantined vs corrected vs held, what does the board see, how does every row
reconcile.

### 4. Find-skills
pandera (or Great Expectations) for declarative checks, pandas for the custom
scans (heaping, duplicate identities, event order), one hardened self-contained
HTML scorecard, a quarantine-ledger discipline.

### 5. Build (gate track)
1. **Preflight** - files exist, columns match; fail loudly with the exact path.
2. **FAIL run** - all checks on the raw data; capture counts, error rates,
   offending samples. Real failures only - never author a failure.
3. **Fixes** - explicit reviewed transforms: quarantine orphans (with reasons),
   map dirty labels (raise on unmapped - never guess), normalize keys via the
   master's own crosswalk, correct provable systematic errors (timezone),
   merge duplicates (stated survivorship policy), HOLD suspected fabrication.
4. **PASS run** - re-execute the same check functions on the fixed tables.
5. **Score + scorecard** - dimension = 100 x (1 - worst check's error rate),
   overall = mean of dimensions, verdict independent of the average. Generate
   the HTML scorecard from the results dict - zero hand-typed numbers.

### 6. Expert review
Panel of 4-6 anonymous senior reviewers - include a DQ/governance lead, an
analytics engineer, a fraud/forensics reviewer for the accuracy screens, and a
board-facing insights lead. Apply fixes, re-run, keep before/after.

## Output format
A runnable `dq_gate.py` + `dq_results.json`, `quarantine_ledger.csv`,
`findings.md`, `everrest_dq_scorecard.html` (self-contained), and ~7 charts.
Everything runs top-to-bottom from a fresh shell.

## Baseline script (start here, then tune)

- `${CLAUDE_SKILL_DIR}/baseline/dq_gate.py` - the real code behind the Everrest
  showcase: preflight, 8 checks across 6 dimensions, fixes with a reconciling
  ledger, computed scorecard.

Run it in a Python env with pandas + matplotlib + pandera. Point it at your raw
files, rewrite the check set to your schema, keep the three rules.
