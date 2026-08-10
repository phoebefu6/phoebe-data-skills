# Everrest warehouse load - data-quality gate findings

**Verdict: SHIP WITH HOLDS.** The load ships. 83 payments from one merchant (suspected fabrication - 100% round amounts against a 0.015% peer rate) stay out of finance rollups until investigated. As received, the load was **BLOCKED**: 5 failures, any one of which corrupts a board metric. All are repaired at ingestion with a full ledger, or held. The verdict is not the score (80.49 in, 99.97 out - not 100, because held rows stay counted until the investigation closes): a gate that averages its way past a blocker is decoration.

## What the bad data was about to cost

| Exposure | Amount | Where it would have landed |
| --- | --- | --- |
| GMV on quarantined lines | $215,076 | revenue-by-product vs finance reconciliation gap |
| Reported amounts on finance hold | $46,200 | suspected fabrication booked as clean revenue |
| Active-buyer overstatement | 3.5% (662 duplicate ids) | every buyer and repeat-rate metric |
| Settlement-lag distortion | -8h on 8.2% of payments | one region's settlement SLA reporting |

## What tripped, dimension by dimension

- **validity / structural schema (pandera)** [pass] - 0 of 107,841 rows (0.00%). types, ranges and keys all conform
- **completeness / customer attributes present** [FAIL -> fixed] - 1,074 of 107,841 rows (1.00%). 1074 line rows arrived with null signup/channel/region - 500 customer ids have no master record (orphan references surfacing as missing attributes after denormalization)
- **validity / category in canon set** [FAIL -> fixed] - 9,572 of 107,841 rows (8.88%). 14 distinct labels arrived for 8 real categories: ['Apparel', 'Beauty', 'Beauty ', 'Electronics', 'Grocary', 'Grocery', 'Home & Living', 'Home & living', 'Pet Supplies', 'Sports & Outdoor', 'Toys & Kids', 'Toys and Kids', 'apparel', 'electronics']
- **consistency / product_id exists in catalog** [FAIL -> fixed] - 2,696 of 107,841 rows (2.50%). 2696 transaction lines reference product ids absent from the catalog master
- **consistency / payment's order exists in transactions** [pass] - 0 of 46,007 rows (0.00%). every payment lands on a shipped order
- **consistency / merchant key formats agree across systems** [FAIL -> fixed] - 107,841 of 107,841 rows (100.00%). transactions use 'M0001' while the merchant master keys on 'MER-0001' - a join on the master's primary key matches 0 of 107841 rows; every merchant attribute would be null downstream
- **consistency / paid_at is not before order_ts** [FAIL -> fixed] - 3,798 of 46,007 rows (8.26%). 3798 payments preceded their own order; every one was in region(s) {'PH': 3798} - the signature of a local-time export (UTC+8) mislabeled as UTC, not of broken data entry
- **timeliness / every feed fresh within SLA** [pass] - 0 of 2 rows (0.00%). every feed's newest event is within 24h of the load line (transactions.order_ts_utc lags 0.9h, payments.paid_at lags 0.0h)
- **uniqueness / one identity, one customer id** [FAIL -> fixed] - 1,324 of 18,888 rows (7.01%). 662 identity groups spanned 1324 customer ids (identical signup timestamp to the second, channel and region) - retention and repeat-rate metrics double-count these people. Merge policy: at 18,888 customers the expected false-pair count on this key is well under one, so the merge is auto-applied here; at millions of signups per year the same key false-merges real people - require a corroborating attribute (hashed email/phone) or route to stewardship before merging
- **accuracy / reported amounts free of round-number heaping** [HOLD] - 85 of 46,007 rows (0.18%). merchant(s) ['M0333'] report ['100%'] of amounts on exact 100s across [85] payments - peer base rate 0.011%; the chance of 100% round amounts across 85 payments by luck is below 1e-336. Routed to investigation and excluded from finance rollups, never 'corrected'. Legitimate merchants can trip a round-share screen (gift cards, fixed-price bundles, COD rounding) - the disambiguators are catalog-price match, distinct-amount diversity and refund ratio

## The fixes, and what they refuse to fix

- 3,742 transaction lines quarantined (orphan customer or product references) - quarantined with reasons, not silently dropped.
- 926 payments followed their quarantined orders out - a fix that strands orphan payments is itself a defect (v1 of this gate shipped 926 of them silently; a reviewer caught it).
- 3,754 payments shifted +8h to UTC. The shift applies to the whole diagnosed region cohort, not just rows showing the symptom - and any residual negative latency outside a diagnosed cohort is quarantined, never blanket-'corrected' under a false audit trail.
- 662 duplicate customer ids merged into their earliest id (match key: signup second + channel + region). The generator planted 800 clone pairs; 662 are observable in the shipped facts - only pairs where both ids transact can double-count, and 800 x 0.91^2 = 662. The gate catches every duplicate that exists in what ships.
- The 14 arriving category labels map to 8 canon categories through an explicit reviewed mapping. The gate raises if a label has no mapping - it never guesses.
- 83 payments from the round-amount merchant are HELD, not edited, and the as-received rows are snapshotted to output/evidence/ with the raw file's sha256 (241e8a5c7b24a2ec...) so the investigation anchors on untouched evidence. Fabrication is a fact about the world; a pipeline that 'corrects' it is lying twice.

## Reconciliation

107,841 lines in = 104,099 loaded + 3,742 quarantined. Payments: 46,007 in = 45,081 loaded + 926 quarantined. Every row is loaded, quarantined, corrected, held or merged - the full trail is `quarantine_ledger.csv`.

## What this gate would have caught in production

Every defect here is a real failure mode from operating retail data platforms: the key-format split breaks every merchant join downstream; the timezone bug quietly corrupts settlement-lag SLAs; duplicate identities inflate active buyers and understate repeat rate; the orphan references make revenue-by-product under-report against finance. The gate exists so these surface at ingestion, with a ledger, instead of in a board meeting.

---

Seed 42. Every number above is computed by `dq_gate.py` against the raw Everrest dump (stage 0 of the lineage). The FAIL run is real - the checks genuinely trip; the PASS run re-executes the same functions on the fixed tables.
