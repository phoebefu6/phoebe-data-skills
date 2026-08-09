---
name: how-to-sales-forecasting
description: Forecast seasonal demand honestly and turn it into a signable inventory buy - run a data-quality gate before measuring anything, separate what the data can prove (weekly seasonality, backtested accuracy) from what it cannot (a peak observed once), then price the unprovable part as a costed newsvendor decision instead of a fake confidence interval. Use when asked to "forecast sales/demand", "how much inventory for <month>", "plan the seasonal buy", "predict next quarter's volume", "is this spike real", or when a forecast must survive a finance review. Walks the 6-step pipeline - input, sample data, objective, find-skills, build (DQ gate + backtests + spike sizing + Monte Carlo + costed commitment), expert review - and outputs a buy paper, not a point estimate.
---

# how-to-sales-forecasting

Data-Science-layer skill (layer 3 of the phoebe-data-skills 4-layer roadmap).
The job is not "fit a model" - it is to put a number in front of a planner and
a P&L owner that both can sign. Most forecasts fail one of three ways: they
measure a data defect as demand, they hide a once-observed event inside a
confidence interval, or they deliver units when the meeting decides dollars.
This skill exists to avoid all three.

Showcase walkthrough (Everrest retail case, real executed charts):
https://github.com/phoebefu6/phoebe-data-skills - `docs/how-to-sales-forecasting/`

## Where this sits in the lineage
`raw dump -> lake -> warehouse -> marts` **-> demand forecast -> inventory buy**.
Reads the clean marts (the output of `how-to-schema-and-warehouse`), and STILL
runs its own data-quality gate - clean-looking marts carried a duplicate-row
defect that manufactured a whole phantom demand spike.

## The three rules that separate it from every forecasting tutorial

1. **DQ gate before any measurement.** Duplicate join keys fan out and create
   phantom demand. In the showcase, a retry bug (600 duplicate order rows)
   manufactured a 1.49x "March spike" that a naive forecast would have bought
   ~$109k of stock for. Dedupe first, report what was removed.
2. **Count observations per seasonal cycle.** Weekly seasonality: ~48 obs per
   weekday - measurable. Annual seasonality: 1 obs per month - NOT measurable.
   A once-observed peak is a parameter, not a finding: declare its year-to-year
   sigma as an input and ship a sensitivity chart, never a fake interval.
3. **The deliverable is a costed decision.** Newsvendor: q* = margin /
   (margin + overstock). Simulate demand, commit at the q* quantile, price the
   buy in dollars, split it into a firm P50 tranche plus an option tranche, and
   sweep BOTH the sigma assumption and the cost rates - the cost rates usually
   move the buy as hard as the model does.

## The 6 steps

### 1. Input
The marts (or the user's tables): orders, order_items, merchants, returns.
Note the grain, the status field (what counts as demand), and whether a
duplicate-key check exists upstream.

### 2. Sample data (only when real data isn't available yet)
Reuse the seeded Everrest marts (seed 42). For a client, skip - use their marts.

### 3. Objective
A decision question with a deadline and a unit: "how many units, and how many
dollars, per category for November - and do we repeat the March buy?" Not
"run a time-series model."

### 4. Find-skills
pandas for the series, statsmodels for Holt-Winters, a rolling-origin backtest
harness, leave-month-out for spike sizing, a bootstrap for within-month
variation, numpy Monte Carlo for the commitment, newsvendor economics for the
service level.

### 5. Build (charts track)
1. **DQ gate**: duplicate keys, join fan-out, status filter. Report counts.
2. **Evidence census**: observations per seasonal cycle; the monthly-dummy trap
   (12 obs, 12 params, R-squared 1.000) shown, not just named.
3. **Short-horizon backtest**: rolling origin, all candidate models, honest
   about which months the folds can and cannot reach.
4. **Long-horizon backtest** at the real planning distance: impute the spike
   months in train (deleting them corrupts weekly phase), de-peaked test, all
   models race; report nominal vs effective (overlap-adjusted) folds.
5. **Spike sizing**: leave-month-out with EVERY spike month held out of the
   baseline fit; bootstrap the multiplier within its month.
6. **Monte Carlo commitment**: baseline error x day variation x declared year
   sigma (median-preserving lognormal, common random numbers across scenarios).
   Per-category newsvendor (own baseline, own multiplier), never a pooled
   quantile split by share.
7. **The buy paper**: dollars at cost, the share riding on the once-observed
   peak, firm/option tranches, weekly staging profile, sigma AND cost-rate
   sensitivity charts.
Honesty gates: every chart from a real executed run; the phantom spike shown
before AND after the gate; unvalidated horizon distances stated on the chart.

### 6. Expert review
Panel of 4-6 anonymous senior reviewers - include a forecasting methodology
lead, a supply-chain planner, and a commercial P&L owner alongside data
engineering. In the showcase this panel found a sign error in the error
propagation, a mean-vs-median lognormal artifact, and the phantom spike itself.
Apply the fixes and re-run; keep the before/after.

## Output format
A runnable `forecast_demand.py` + `forecast.json` (every computed value),
`forecast_commitments.csv` (units + dollars per category),
`november_weekly_staging.csv`, `findings.md` (the buy paper), and ~18 charts.
Deterministic: seeded generators per random purpose, two runs byte-identical.

## Baseline script (start here, then tune)

This skill ships a runnable baseline in `baseline/` - the real code behind the
Everrest showcase. Read it, then tune it to the user's marts:

- `${CLAUDE_SKILL_DIR}/baseline/forecast_demand.py` - the full pipeline: DQ
  gate, backtests, spike sizing, Monte Carlo, costed commitment, buy paper.

Run it in a Python env with pandas + numpy + matplotlib + statsmodels. Point
`MARTS` at the user's tables, set the calendar constants (`SPIKES`,
`PHANTOM_MONTH`, `PLAN_FROM`, `PLAN_MONTH`) for their window - the script fails
loudly with instructions if they do not fit - and set `MARGIN_RATE` /
`OVERSTOCK_RATE` / `CATEGORY_COST_OVERRIDES` to the rates finance confirms.
