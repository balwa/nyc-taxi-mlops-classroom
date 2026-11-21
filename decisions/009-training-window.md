# 009: Training window and holdout

Stage: S2 · Date: 2026-11-21 · Author: Tanmay Balwa · Drafted by agent: yes

## Choice

Train on **2024-01..2024-03**, evaluate on the next month, **2024-04**. The zone-pair distance lookup (`est_distance_miles`) is computed from the same three months.

In the pipeline this is a rule, not fixed dates: the holdout is the latest month in `staging.trip_features`, and the window is the three months before it. Today that gives the months above; when a later month lands, the window slides forward by itself. (The agent chose this reading; say so if you want fixed dates instead.)

## Rejected alternative

Shorter windows: 2024-02..03 (v2 MAE 3.67) or 2024-03 alone (3.69). They are cheaper to train and, for v2, no worse on the 2024-04 holdout. A random split of the same months is also rejected: it would let the model see the future.

## Why

<!-- Student: rewrite in your own words. -->
The holdout is the month after the window, so the model is judged on data it could not have seen, as in production. On a 10% sample, v2's MAE on 2024-04 was 3.69 with three months, 3.67 with two and 3.69 with one, so the window length barely mattered for v2. Three months uses all data before the holdout and gives the distance lookup the most pairs; v1, the baseline, improves with length (4.51, 4.33, 4.26), which makes the comparison fairer to it. The cost is the longest training time, and with only four months of data the window can't test whether older months help or hurt.

## What would show this was wrong

A later month where a shorter window clearly beats this one (the data drifts and old months hurt); the drift report showing the oldest month differs a lot from the newest; or a holdout MAE that keeps rising while training on all three months.
