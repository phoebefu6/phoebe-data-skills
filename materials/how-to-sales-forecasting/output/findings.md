# Everrest November 2026 buy paper

Seed 42. Every number below is computed by `forecast_demand.py` from the Everrest marts (2025-07-01 to 2026-06-30, 365 days, 140,219 delivered units after the data-quality gate).

## The decision

Stage **35,338 units** for November 2026: **$854,763 at retail, $683,810 committed at cost** (unit cost taken as 80% of price - the complement of the stated margin). Of that cash, $432,082 (63% of the buy) rides on the November peak repeating at 2.18x, an event observed once. P50 is 30,536 units ($590,814 at cost) and P90 is 42,699 ($826,145): a 39% band between the middle and the cautious case, because a five-month-ahead forecast of a once-observed peak deserves a wide band and gets one here. Being wrong on the service level costs about $19,195 either way at the optimum.

**How to commit it.** Place the P50 tranche (**30,536 units, $590,814 at cost**) as the firm buy now. Hold the remaining 4,802 units ($92,996) as a late-cut or reserved-capacity option, released on the September and October run-rate against the +2.4%/month baseline trend. The forecast is validated to 120 days and November is 153 days out - the option tranche is what buys the right to be wrong in that unvalidated tail for $92,996 instead of the full $683,810. Weekly staging profile in `november_weekly_staging.csv`.

## The March buy is cancelled - the spike was never demand

Read naively, March 2026 runs at 1.49x its baseline - 5,645 apparent extra units, and a repeat buy would stage $109,212 of stock at cost. The data-quality gate found the driver no forecast could: **600 duplicate order_id rows** - a retry bug, every one of them in March - whose join against order_items fans out about 4x. Deduplicated, March sits at 1.00x baseline: an ordinary month. The v1 draft of this analysis skipped the gate, measured the phantom at 1.49x, could not name a driver, and left a six-figure option open on it. The recommendation is an engineering ticket, not a purchase order: fix the retry bug, add a duplicate-key check to ingestion, stock nothing.

## What was measured

- The defect: 600 duplicate order rows across 600 orders, 1439 doubled item lines dropped, all in 2026-03.
- Weekday seasonality: 47 to 49 observations per weekday on de-peaked days; weekend runs 45% above weekdays.
- Short-horizon model selection: 5 candidates, rolling origin, 8 folds, 28-day horizon. Winner **Holt-Winters (weekly)** at 12.4% MAPE. Honest gap: no fold reaches the spike month - it sits before the first valid test origin - so the spike is validated by leave-month-out, not by the backtest.
- Long-horizon selection: all 5 candidates at 120 days, spike month imputed in train, de-peaked test. Winner **log-linear + weekday** at 10.7% MAPE. Honest caveat: the 3 fold windows overlap - about 2 independent comparisons.
- Underlying trend on de-peaked days: +2.4% per month.
- The November lift against a baseline that never saw it: 2.18x, 12,067 extra units.

## What was not measured, and is not pretended

- That November repeats at all: n = 1 year. The bootstrap band covers day-to-day variation inside the one November observed - a 5% spread, which is why it is not used alone.
- Year-to-year variation of the multiplier is an INPUT: sigma = 25%. Nothing in 12 months of data can estimate it - and the commit barely cares: across sigma 0% to 50% the buy moves 30,407 to 39,824 units, about 31%. The P90 is not robust - it runs 30,828 to 57,823 over the same range. The buy is safe against this assumption; the worst case is not.
- Accuracy at the planning horizon: validation reaches 120 days, the November buy is 153 days out.
- The baseline uncertainty rests on 3 fold residuals - thin, and said so on the chart.
- Category split comes from the single November observed; the largest category share moves 0.9 points if taken from all 12 months instead.
- Per-category commits are simulated per category (own baseline, own multiplier, shared year draw) and sum to 35,338 - 790 units above the pooled platform quantile. That gap is the price of promising each category its own service level instead of spending the pooling benefit without earning it.

## Commitment table

| Category | Nov share | P50 | Commit | Commit $ (cost) | P90 | Buffer over P50 |
| --- | --- | --- | --- | --- | --- | --- |
| Toys & Kids | 14.1% | 4,384 | **5,083** | $103,419 | 6,141 | 699 |
| Grocery | 13.5% | 4,311 | **4,984** | $93,049 | 6,022 | 674 |
| Beauty | 12.7% | 4,222 | **4,898** | $91,606 | 5,911 | 676 |
| Electronics | 12.8% | 4,099 | **4,727** | $93,968 | 5,723 | 628 |
| Apparel | 13.9% | 3,879 | **4,485** | $87,799 | 5,422 | 606 |
| Home & Living | 12.2% | 3,879 | **4,477** | $87,203 | 5,405 | 598 |
| Pet Supplies | 10.7% | 3,107 | **3,600** | $69,633 | 4,350 | 492 |
| Sports & Outdoor | 10.1% | 2,655 | **3,084** | $57,133 | 3,725 | 429 |

Totals: **35,338 units, $683,810 at cost**. The service level is 0.71 in every row because the cost rates are assumed uniform - `CATEGORY_COST_OVERRIDES` in the script is where a planner sets real per-category economics (a perishable category belongs at a much lower q*).

## The two numbers finance must confirm before this is approved

Margin rate 20% and overstock rate 8% of unit price set q* = 0.71 and therefore the entire buy. There is no COGS field in the marts, so they are inputs, not findings - and they move the commitment by $154,292 of committed cash across plausible rates, the same order of magnitude as the sigma assumption (about $182,196). Neither is measurable from the marts; both are declared inputs with a sensitivity chart. On rates typical of peak-season stock (35% margin, 20% overstock) the commit falls to 32,706 units. See `cost_sensitivity.png`.

## Other assumptions a reader may want to change

- Year-to-year sigma 25% on the spike multiplier (median-preserving lognormal).
- Demand is committed gross of returns. 7.0% of units sit on orders that later had a return - an order-level upper bound (the returns mart has no line detail), and returned units re-enter supply mid-month, so the commit is not padded for them.
- Units, not revenue, for the demand model: the top merchant by units (M0172) is 0.34% of units, so the outlier handling a revenue metric needs does not apply here. Dollars enter at the commitment step.

## The data request that would end the guessing

One more November. Until then: log a promotion and campaign calendar as first-class fields, add a duplicate-key check to ingestion so the next retry bug is caught at load time, and record supplier lead time, MOQ and pack size per category so the commitment table can become a purchase order.
