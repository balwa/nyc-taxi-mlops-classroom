"""raw_trips: one month of trips COPYed from the data bucket into ingest.raw_trips.

Decisions 005 and 006: Parquet COPY (not Spectrum); a reload is idempotent because the month is
COPYed into a temp table, then, in the same transaction, its old rows are deleted and the new ones
inserted. A failed COPY rolls everything back, so a month is never half-loaded or missing.
ingest.raw_trips is DISTSTYLE EVEN with SORTKEY (source_file): every read filters by source_file.
The landing columns come from contracts/trips.schema.yaml, in order (Parquet COPY maps by position).
"""

import dagster as dg

from ..contracts import redshift_columns, trips_schema
from ..partitions import source_file, trip_months
from ..resources import DataBucket, RedshiftData

LANDING = "raw_trips_load"  # temp table, lives for the batch's session


def load_statements(month: str, uri: str) -> list[str]:
    """All statements that load one month. `month` and `uri` are validated by the caller's helpers."""
    file = source_file(month)
    cols = redshift_columns(trips_schema())
    return [
        "create schema if not exists ingest",
        f"create table if not exists ingest.raw_trips (source_file varchar(64) not null, {cols}) "
        "diststyle even sortkey (source_file)",
        f"create temp table {LANDING} ({cols})",
        f"copy {LANDING} from '{uri}' iam_role default format as parquet",
        f"delete from ingest.raw_trips where source_file = '{file}'",
        f"insert into ingest.raw_trips select '{file}', * from {LANDING}",
        f"drop table {LANDING}",
    ]


@dg.asset(partitions_def=trip_months, deps=["trip_files"], group_name="ingest", kinds={"redshift", "s3"}, pool="redshift")
def raw_trips(context: dg.AssetExecutionContext, redshift: RedshiftData, data_bucket: DataBucket) -> dg.MaterializeResult:
    month = context.partition_key
    uri = data_bucket.trip_uri(month)  # validates the month
    # One execute() call = one transaction in one session (see RedshiftData.execute).
    redshift.execute(*load_statements(month, uri))
    rows = redshift.scalar(f"select count(*) from ingest.raw_trips where source_file = '{source_file(month)}'")
    return dg.MaterializeResult(metadata={"rows": dg.MetadataValue.int(int(rows)), "source": uri})
