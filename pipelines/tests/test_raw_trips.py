"""raw_trips: the load is one transaction, in the order the idempotence decision (005) needs."""

import dagster as dg
import pytest
from fakes import LOG, fake_bucket, fake_redshift

from labpipes.contracts import redshift_columns, trips_schema
from labpipes.defs.raw_trips import load_statements, raw_trips

URI = "s3://data/trips/yellow_tripdata_2024-03.parquet"


def test_load_copies_then_deletes_then_inserts_that_month_only():
    sqls = load_statements("2024-03", URI)
    kinds = [s.split()[0] + " " + s.split()[1] for s in sqls]
    assert kinds.index("copy raw_trips_load") < kinds.index("delete from") < kinds.index("insert into")
    assert any(s == "delete from ingest.raw_trips where source_file = 'yellow_tripdata_2024-03.parquet'" for s in sqls)
    assert f"copy raw_trips_load from '{URI}' iam_role default format as parquet" in sqls


def test_table_follows_decision_006_and_the_contract():
    ddl = next(s for s in load_statements("2024-03", URI) if s.startswith("create table if not exists ingest.raw_trips"))
    assert "diststyle even" in ddl and "sortkey (source_file)" in ddl
    assert redshift_columns(trips_schema()) in ddl


def test_a_bad_month_never_reaches_sql():
    with pytest.raises(ValueError):
        load_statements("2024-03'; drop table x; --", URI)


def test_asset_runs_the_load_as_one_batch_and_reports_rows():
    instance = dg.DagsterInstance.ephemeral()
    instance.add_dynamic_partitions("trip_months", ["2024-03"])
    rs = fake_redshift(rows=42)
    result = dg.materialize(
        [raw_trips], partition_key="2024-03", instance=instance,
        resources={"redshift": rs, "data_bucket": fake_bucket({})},
    )
    assert result.success
    assert LOG[0] == "create schema if not exists ingest"
    assert any(s.startswith("copy raw_trips_load from 's3://data/trips/yellow_tripdata_2024-03.parquet'") for s in LOG)
    assert result.asset_materializations_for_node("raw_trips")[0].metadata["rows"].value == 42
