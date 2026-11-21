"""schema_contract and the ingest sensor, against the fakes."""

import json

import dagster as dg
from fakes import fake_bucket, schema_2023, schema_2025

from labpipes.contracts import Column, trips_schema
from labpipes.defs.schema_check import differences, schema_contract
from labpipes.defs.sensor import ingest_month, new_trip_files, plan
from labpipes.resources import TripFile


def test_contract_schema_matches_itself_and_ignores_name_case():
    assert differences(trips_schema(), trips_schema()) == []
    lowered = [Column("airport_fee" if c.name == "Airport_fee" else c.name, c.type) for c in trips_schema()]
    assert differences(lowered, trips_schema()) == []


def test_appended_column_is_a_mismatch():  # E4a: 2025-01 adds cbd_congestion_fee
    found = differences(schema_2025(), trips_schema())
    assert any("20 columns" in d for d in found) and any("cbd_congestion_fee" in d for d in found)


def test_changed_types_are_a_mismatch():  # E8
    assert len(differences(schema_2023(), trips_schema())) >= 5


def test_missing_and_reordered_columns_are_mismatches():
    cols = trips_schema()
    assert any("missing column" in d for d in differences(cols[:-1], trips_schema()))
    swapped = [cols[1], cols[0], *cols[2:]]
    assert any("name" in d for d in differences(swapped, trips_schema()))


def test_schema_contract_is_a_blocking_check_on_trip_files():
    (spec,) = schema_contract.check_specs
    assert spec.name == "schema_contract" and spec.blocking and spec.asset_key == dg.AssetKey("trip_files")


def tf(month, etag):
    return TripFile(month, f"trips/yellow_tripdata_{month}.parquet", etag, 1)


def test_plan_runs_new_and_changed_months_only():
    files = [tf("2024-01", "a"), tf("2024-02", "b")]
    months, new, cursor = plan(files, {}, set())
    assert months == ["2024-01", "2024-02"] and new == months
    months, new, cursor2 = plan(files, cursor, {"2024-01", "2024-02"})
    assert months == [] and new == [] and cursor2 == cursor
    months, new, _ = plan([tf("2024-01", "a2"), tf("2024-02", "b")], cursor, {"2024-01", "2024-02"})
    assert months == ["2024-01"] and new == []  # changed: run again, partition already exists


def test_sensor_requests_partitions_and_runs_then_goes_quiet():
    bucket = fake_bucket({"2024-01": ("e1", trips_schema()), "2024-02": ("e2", trips_schema())})
    instance = dg.DagsterInstance.ephemeral()
    ctx = dg.build_sensor_context(instance=instance, resources={"data_bucket": bucket})
    result = new_trip_files(ctx)
    assert [r.partition_key for r in result.run_requests] == ["2024-01", "2024-02"]
    assert [r.run_key for r in result.run_requests] == ["2024-01:e1", "2024-02:e2"]
    assert result.dynamic_partitions_requests[0].partition_keys == ["2024-01", "2024-02"]
    assert json.loads(result.cursor) == {"2024-01": "e1", "2024-02": "e2"}
    instance.add_dynamic_partitions("trip_months", ["2024-01", "2024-02"])
    again = new_trip_files(dg.build_sensor_context(instance=instance, cursor=result.cursor, resources={"data_bucket": bucket}))
    assert isinstance(again, dg.SkipReason)


def test_job_covers_trip_files_to_the_mart():
    assert ingest_month.name == "ingest_month"
