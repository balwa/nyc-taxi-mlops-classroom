"""S1: the ingest sensor (and the job it starts).

Watches trips/ in the data bucket. When a month's file appears or its ETag changes, the month is added
to the trip_months partitions and one run is requested for it, from trip_files through zone_hour_stats.
The blocking checks inside that run (schema_contract, then the stg_trips quality gates) stop whatever
is downstream of them. taxi_zones is in the job so the first run has the zone names the mart joins.

The cursor remembers {month: etag} for what was already requested. run_key is month + etag: a repeated
tick is a no-op, and a changed file gets a fresh run. Patterns: pipelines/reference/patterns.py.
"""

import json

import dagster as dg

from ..partitions import trip_months
from ..resources import DataBucket

ingest_month = dg.define_asset_job(
    "ingest_month",
    selection=dg.AssetSelection.assets("taxi_zones", "trip_files", "raw_trips", "stg_trips", "zone_hour_stats"),
    description="One month: footer check, COPY, staging, quality gates, then the mart.",
)


def plan(files: list, seen: dict, known_partitions: set[str]) -> tuple[list[str], list[str], dict]:
    """(months to run, months to add as partitions, new cursor). `files` are TripFile-likes."""
    changed = [f for f in files if seen.get(f.month) != f.etag]
    new_partitions = [f.month for f in changed if f.month not in known_partitions]
    cursor = {**seen, **{f.month: f.etag for f in changed}}
    return [f.month for f in changed], new_partitions, cursor


@dg.sensor(job=ingest_month, minimum_interval_seconds=60, description="Runs ingest_month for each new or changed trip file.")
def new_trip_files(context: dg.SensorEvaluationContext, data_bucket: DataBucket):
    files = data_bucket.trip_files()
    seen = json.loads(context.cursor or "{}")
    known = set(context.instance.get_dynamic_partitions(trip_months.name))
    months, new_partitions, cursor = plan(files, seen, known)
    if not months:
        return dg.SkipReason("no new or changed trip files")
    etag = {f.month: f.etag for f in files}
    return dg.SensorResult(
        run_requests=[dg.RunRequest(run_key=f"{m}:{etag[m]}", partition_key=m) for m in months],
        dynamic_partitions_requests=[trip_months.build_add_request(new_partitions)] if new_partitions else [],
        cursor=json.dumps(cursor),
    )
