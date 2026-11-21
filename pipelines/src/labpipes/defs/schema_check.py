"""S1: the schema_contract check on trip_files.

Compares the landed file's Parquet footer (the DataBucket resource reads it, nothing is downloaded)
with contracts/trips.schema.yaml, before raw_trips runs COPY. contracts/platform.yaml says this check
is blocking: Parquet COPY maps columns by position, so a moved schema fails or, worse, loads shifted
columns.

What counts as a mismatch is the contract's own rule: same number of columns, in the same order, with
equal Parquet storage types; names compare case-insensitively (TLC renamed airport_fee to Airport_fee).
"""

from dataclasses import asdict

import dagster as dg

from ..contracts import Column, trips_schema
from ..partitions import trip_months
from ..resources import DataBucket


def differences(actual: list[Column], expected: list[Column]) -> list[str]:
    """Human-readable mismatches between a file's columns and the contract ([] if they agree)."""
    found = []
    if len(actual) != len(expected):
        found.append(f"{len(actual)} columns, the contract has {len(expected)}")
    for i, (a, e) in enumerate(zip(actual, expected, strict=False), start=1):
        if a.name.lower() != e.name.lower():
            found.append(f"column {i}: name {a.name!r}, expected {e.name!r}")
        if a.type != e.type:
            found.append(f"column {i} ({e.name}): type {a.type}, expected {e.type}")
    for extra in actual[len(expected) :]:
        found.append(f"extra column {extra.name!r} ({extra.type}) after the contract's last column")
    for missing in expected[len(actual) :]:
        found.append(f"missing column {missing.name!r} ({missing.type})")
    return found


@dg.asset_check(asset="trip_files", name="schema_contract", partitions_def=trip_months, blocking=True,
                description="The file's Parquet footer matches contracts/trips.schema.yaml (count, order, types).")
def schema_contract(context: dg.AssetCheckExecutionContext, data_bucket: DataBucket) -> dg.AssetCheckResult:
    footer = data_bucket.footer(context.partition_key)
    found = differences(footer.columns, trips_schema())
    return dg.AssetCheckResult(
        passed=not found,
        severity=dg.AssetCheckSeverity.ERROR,
        description="matches the contract" if not found else "; ".join(found[:5]) + (f" (+{len(found) - 5} more)" if len(found) > 5 else ""),
        metadata={
            "differences": dg.MetadataValue.json(found),
            "columns": dg.MetadataValue.json([asdict(c) for c in footer.columns]),
            "num_rows": dg.MetadataValue.int(footer.num_rows),
        },
    )
