# 004: Blocking vs warning checks, and the thresholds

Stage: S1 · Date: 2026-11-21 · Author: Tanmay Balwa · Drafted by agent: yes

## Choice

Checks on `staging.stg_trips`, per month. Rate limits are 5x the worst of the four real months (2024-01..04, measured in Redshift).

**Block** (asset checks with `blocking=True`):
- no null pickup/dropoff time or zone ID (limit 0; real months: 0)
- pickup outside the file's month: at most 3.2e-5 of rows (real worst 6.4e-6)
- at most 5 exact duplicate rows (real months: 0 or 1)
- null group (passengers and rate code missing together) under 15% (real months: 4.7%, 6.2%, 11.9%, 11.6%)
- at least 1,000,000 rows (real months: 2.96M to 3.58M)

**Warn only** (severity WARN, `blocking=False`), each at 5x its worst real month: negative duration 0.016%, trips under 1 minute 5.8%, unknown pickup zone 2.0%, unknown dropoff zone 4.7%, distance <= 0 12%, fare <= 0 8.4%, negative total 6.2%, zero passengers 5.7%.

The values are in `LIMITS` in `pipelines/src/labpipes/defs/quality.py`.

## Rejected alternative

Zero tolerance on structural checks, and relative-to-previous-month thresholds. Zero tolerance would block every real month (there are always 9 to 23 stray pickup dates, and one duplicate in February). Month-over-month thresholds have no baseline for the first month, and a second corrupt month looks normal after a first.

## Why

<!-- Student: rewrite in your own words. Agent assumptions to confirm or change: unknown zone IDs (outside 1-263) warn rather than block; the null group blocks at 15%. -->
Real months always contain some bad rows, so the gate has to sit above the observed baseline and below what a corrupt month would show. A 5x margin on the worst real month gives that room. The noisy fields (distance, fare, passengers) swing too much between months to be trusted as a gate, so they warn. The cost: a month with, say, 11% non-positive distances still passes with a warning.

## What would show this was wrong

A real month that is blocked for a benign reason (for example a null group that keeps rising past 15%), or a bad month that reaches `zone_hour_stats` with only warnings. Four months of history is a small baseline: revisit after more months land.
