# 005: COPY vs Spectrum, and how a reload stays idempotent

Stage: S1 · Date: 2026-11-21 · Author: Tanmay Balwa · Drafted by agent: yes

## Choice

Load each month into `ingest.raw_trips` with Parquet `COPY` (using the cluster's default role, `iam_role default`), not Spectrum. A reload is idempotent by delete-then-insert in one transaction: COPY the file into a temp table, then delete rows with that `source_file` and insert from the temp table. A failure rolls the whole thing back.

## Rejected alternative

Spectrum: an external table over the Parquet files in S3, with no load step. It has no duplicates to manage, but every query scans S3, there are no sort or distribution keys to tune, and `stg_trips.sql` (which reads `ingest.raw_trips` filtered by `source_file`) would need reworking.

For idempotence, the rejected alternative is "skip if the file's rows already exist". A file that changes under the same name would never reload, which defeats the sensor's "appears or changes" trigger.

## Why

<!-- Student: rewrite in your own words. -->
The existing staging SQL and the data-quality checks read a real table, so COPY fits what's given and keeps queries local to the cluster. Delete-then-insert matches how `stg_trips` already reloads a month, and doing it in one transaction means a failed load never leaves a month half-loaded or missing. Costs: load time and storage for about 13M rows, and a month is briefly absent inside the transaction, so readers see either the old or the new data.

## What would show this was wrong

A load that takes too long or blocks other writers (the `redshift` pool serializes them); a changed file that leaves duplicates or a gap; or data volume growing enough that storing a second copy becomes a cost problem.
