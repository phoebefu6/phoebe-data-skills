---
name: how-to-rfm
description: Run a decision-first RFM customer segmentation with Claude + Python on any transaction history. Use when handed customer/order data and asked to "segment customers", "run RFM", "who are our best customers", "who is churning", "where should we spend retention/CRM budget", "find high-value customers", or before designing any lifecycle/loyalty/win-back campaign. Walks the 6-step pipeline - input, sample data (if none yet), objective, find-skills, code with real executed charts, expert review - and outputs segments ranked by dollar at stake with a budget recommendation.
---

# how-to-RFM-using-claude-python

Decision-first RFM: the output is a ranked budget recommendation - which segments to
protect and which to win back, each with a dollar figure - not a table of scores.

Showcase walkthrough (Everrest retail case, real executed charts):
https://github.com/phoebefu6/phoebe-data-skills - `docs/how-to-rfm-using-claude-python/`

## The 6 steps

### 1. Input
Collect the transaction tables (customers, orders, order_items or equivalent) and the
business context - specifically the decision on the table (retention budget, win-back
campaign, VIP program). RFM needs only: a customer key, an order timestamp, and an order
value. Confirm the grain and pick the analysis reference date ("today").

### 2. Sample data (only when real data isn't available yet)
Write a seeded generator that draws each customer from a lifecycle archetype (champion,
loyal, at-risk, can't-lose-them, hibernating, one-and-done...) so the segmentation has
structure to recover. Plant patterns on purpose - whale concentration, high-value lapsers,
a one-and-done acquisition channel, a promo cohort that never reactivated, a returns-heavy
group - and keep a ground-truth label column to validate against. With real data, skip this.

### 3. Objective
Frame ONE budget decision ("where should the CRM team spend Q3 retention budget, and who
is quietly most valuable?") plus 3-5 sub-questions (value concentration, lapsing high-value
customers, low-value channels, segment sizes, best next dollar). Every chart must serve one.

### 4. Find-skills
List the tools before coding: pandas qcut for quintile scoring (rank-break frequency ties),
the standard 11-segment RFM map, dataviz discipline (treemap for size, bubble map for the
budget call), and an insights playbook to rank segments by dollar opportunity.

### 5. Code + charts
One script, sectioned:
1. **Data-quality gate FIRST**: score Monetary and Frequency on DELIVERED revenue only -
   returned/cancelled orders are not value and will inflate the wrong customers. Fix a
   reference date for Recency.
2. **Score**: R by recency quintile, F by frequency rank quintile (rank avoids qcut tie
   errors), M by monetary quintile. Combine F and M into FM for the segment map.
3. **Segment**: map (R, FM) to the 11 standard segments, evaluating value-critical segments
   first (Champions, then Can't-Lose-Them using M so whale lapsers aren't missed).
4. **Business questions on the segments**: value concentration (pareto), segment size
   (treemap), segment by acquisition channel (finds one-and-done channels), value per
   segment (box), cohort reactivation, and a budget map (avg recency x avg value, bubble =
   size) that IS the recommendation.
Rules: fixed seed + reference date stated in output; every chart titled with its FINDING;
name the act-now segments; 300 DPI PNGs; aim for 10+ chart types; kill any chart with no
budget action attached. If sample data was generated, add a validation chart confirming
segments recover the planted archetypes.

### 6. Expert review
Convene a panel of 4-6 senior reviewer agents (10+ years in data, insights, business).
Review the code + outputs through these lenses, apply the fixes, re-run:
- **Code & pipeline**: is monetary gated to delivered revenue? returns excluded?
- **Scoring rigor**: frequency scored on rank (not raw qcut)? recency from a fixed date? segments named, not raw RF codes?
- **Segment framing**: is the acquisition-channel view present (one-and-done story)? every chart a finding?
- **Budget ROI**: does every segment carry a $ figure? is there a ranked budget recommendation?
- **QA & reproducibility**: do segments recover the planted archetypes on a clean re-run?
Keep the before/after - review that changes nothing is theater.

## Output format
`findings.md`: segments ranked by dollar at stake, each 2-3 sentences (segment, size, $,
recommended budget action), plus a segment summary table. Charts in a `charts/` folder.
Script(s) runnable top-to-bottom from a fresh shell.

## Baseline script (start here, then tune)

This skill ships a runnable baseline in `baseline/` - the real code behind the
Everrest showcase. Read it as the starting point, then tune it to the user's
schema and question:

- `${CLAUDE_SKILL_DIR}/baseline/rfm_everrest_v2.py` - the RFM segmentation + segment actions
- `${CLAUDE_SKILL_DIR}/baseline/generate_everrest_rfm.py` - seeded sample data (skip when real data exists)

Run it in a Python env with pandas + matplotlib (plus any extras noted). Point it
at the user's data, then change what the use case needs - new columns, a different
decision question, their industry. The showcase page walks the full example.
