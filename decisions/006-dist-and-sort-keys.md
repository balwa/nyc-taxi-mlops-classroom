# 006: Distribution and sort keys for ingest.raw_trips

Stage: S1 · Date: 2026-11-21 · Author: Tanmay Balwa · Drafted by agent: yes

## Choice

`ingest.raw_trips`: `DISTSTYLE EVEN`, `SORTKEY (source_file)`. `staging.stg_trips` keeps the given `sortkey (pickup_at)` from its SQL file.

## Rejected alternative

For the sort key: `tpep_pickup_datetime`, which would match `stg_trips`' own key and time-range queries but leave the `source_file` filter unable to skip blocks. For distribution: `KEY` on `PULocationID`, which co-locates a zone's rows for the mart's group-by if the cluster grows to two nodes, but risks skew toward busy zones.

## Why

<!-- Student: rewrite in your own words. -->
Every read of `raw_trips` filters by `source_file`: the delete in the idempotent reload and the `where source_file = ...` in `stg_trips.sql`. Sorting on it lets Redshift skip every other month's blocks. The cluster has one node, so distribution moves no data between nodes either way, and EVEN avoids zone skew without a tuning story to defend. Cost: queries on `raw_trips` by time get no block skipping (they run against `stg_trips`, which is sorted by `pickup_at`).

## What would show this was wrong

Slow `stg_trips` builds despite the sort key; the cluster growing to two nodes with the mart's join and group-by shuffling data; or query plans (`EXPLAIN`, `svl_query_summary`) showing scans of other months' blocks.
