# 008: Promotion metric and margin

Stage: S2 · Date: 2026-11-21 · Author: Tanmay Balwa · Drafted by agent: yes

## Choice

A new version becomes `challenger` only if its holdout MAE (`mae_min`) is at least **2% lower** than what it is compared against (the champion, or the v1 baseline before there is one) **and** its p95 single-row latency is at most **20 ms**. The gate looks at overall MAE only; the slice MAEs (airport, Manhattan, outer, night) are logged and tagged but don't gate.

## Rejected alternative

For the margin: "any improvement" (strictly lower MAE), an absolute 0.1 min, and 5%. Any improvement would promote on noise, since MAE moves about 0.2 min between months. For the slice guard: "no slice may regress", which catches a model that trades one group for another but blocks good models on noisy small slices.

## Why

<!-- Student: rewrite in your own words. -->
Measured on a 10% sample (2024-04 holdout, trained on 01..03): v1 MAE 4.26, v2 MAE 3.69, so v2 beats v1 by 13% and passes easily. v2 beats v1 on every slice, so overall MAE is enough today. 2% of about 3.7 minutes is about 0.07 minutes, smaller than the ~0.2 minute spread between months, so a model that just got lucky on one holdout could still pass: this margin guards against regressions more than it proves a real gain. Latency was 0.7 to 1.0 ms p95 on a laptop; 20 ms is loose enough for a slower serving host and still small next to a network call.

## What would show this was wrong

A promoted version that serves noticeably worse for one group (airport or night trips) while overall MAE looks fine; a version promoted for a gain that disappears on the next month; or serving's real p95 latency approaching 20 ms.
