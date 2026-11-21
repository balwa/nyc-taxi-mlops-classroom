"""S1: data-quality checks on stg_trips (nulls, ranges, duplicates, row counts).

Every threshold lives in LIMITS below, with the real-month figure it came from. Rate limits are
5x the worst of the four real months (2024-01..04, measured in Redshift on 2024-11-21); structural
checks block, the noisy ones only warn (decisions/004-quality-checks.md).
"""

from dataclasses import dataclass

import dagster as dg

from ..partitions import check_month, trip_months
from ..resources import RedshiftData

TABLE = "staging.stg_trips"
# stg_trips columns that identify a trip, for the duplicate check.
TRIP_COLUMNS = (
    "vendor_id, pickup_at, dropoff_at, pickup_zone_id, dropoff_zone_id, passenger_count, "
    "trip_distance, ratecode_id, payment_type, fare_amount, total_amount"
)


@dataclass(frozen=True)
class RateLimit:
    """`where` picks the bad rows; the check fails when bad/rows exceeds max_rate."""

    name: str
    where: str
    max_rate: float
    blocking: bool
    description: str


# Real-month worst rates (Jan-Apr 2024) and the 5x limits derived from them.
LIMITS = [
    # Structural: block.
    RateLimit("no_null_times_or_zones", "pickup_at is null or dropoff_at is null or pickup_zone_id is null or dropoff_zone_id is null", 0.0, True,
              "Pickup/dropoff time and zone IDs are never null (0 in all four real months)."),
    RateLimit("pickups_inside_month", "to_char(pickup_at, 'YYYY-MM') <> trip_month", 3.2e-5, True,
              "Pickups fall inside the file's month (worst real month 6.4e-6, a few stray dates each)."),
    # Block on the null group: passengers, rate code and (not in stg) flag and surcharges are null together.
    RateLimit("null_group_under_15_percent", "passenger_count is null or ratecode_id is null", 0.15, True,
              "Rows missing passengers and rate code stay under 15% (real months: 4.7%, 6.2%, 11.9%, 11.6%)."),
    # Noisy: warn.
    RateLimit("negative_duration", "duration_min < 0", 1.6e-4, False, "Negative durations (worst real month 3.3e-5)."),
    RateLimit("short_duration", "duration_min > 0 and duration_min < 1", 0.058, False, "Trips under a minute (worst real month 1.16%)."),
    RateLimit("unknown_pickup_zone", "pickup_zone_id not between 1 and 263", 0.020, False, "Pickup zone outside 1-263 (worst 0.41%)."),
    RateLimit("unknown_dropoff_zone", "dropoff_zone_id not between 1 and 263", 0.047, False, "Dropoff zone outside 1-263 (worst 0.95%)."),
    RateLimit("nonpositive_distance", "trip_distance <= 0", 0.12, False, "Distance of zero or less (worst real month 2.43%)."),
    RateLimit("nonpositive_fare", "fare_amount <= 0", 0.084, False, "Fare of zero or less (worst real month 1.68%)."),
    RateLimit("negative_total", "total_amount < 0", 0.062, False, "Negative total (worst real month 1.24%)."),
    RateLimit("zero_passengers", "passenger_count = 0", 0.057, False, "Zero passengers (worst real month 1.13%)."),
]

MIN_ROWS = 1_000_000  # block below this (real months: 2.96M-3.58M)
MAX_DUPLICATES = 5  # block above this many exact duplicates (real months: 0 or 1)


def severity(blocking: bool) -> dg.AssetCheckSeverity:
    return dg.AssetCheckSeverity.ERROR if blocking else dg.AssetCheckSeverity.WARN


def measure_rate(redshift: RedshiftData, month: str, where: str) -> tuple[int, int]:
    """(rows, bad rows) for one month. `month` is validated before it enters the SQL text."""
    month = check_month(month)
    row = redshift.query(
        f"select count(*) as rows, coalesce(sum(case when {where} then 1 else 0 end), 0) as bad "
        f"from {TABLE} where trip_month = '{month}'"
    )[0]
    return int(row["rows"]), int(row["bad"])


def rate_result(limit: RateLimit, rows: int, bad: int) -> dg.AssetCheckResult:
    rate = bad / rows if rows else 0.0
    return dg.AssetCheckResult(
        passed=rate <= limit.max_rate,
        severity=severity(limit.blocking),
        description=f"{bad} of {rows} rows ({rate:.4%}); limit {limit.max_rate:.4%}",
        metadata={
            "rows": dg.MetadataValue.int(rows),
            "bad_rows": dg.MetadataValue.int(bad),
            "rate": dg.MetadataValue.float(rate),
            "max_rate": dg.MetadataValue.float(limit.max_rate),
        },
    )


def _rate_check(limit: RateLimit):
    @dg.asset_check(asset="stg_trips", name=limit.name, partitions_def=trip_months, blocking=limit.blocking,
                    description=limit.description)
    def check(context: dg.AssetCheckExecutionContext, redshift: RedshiftData) -> dg.AssetCheckResult:
        rows, bad = measure_rate(redshift, context.partition_key, limit.where)
        return rate_result(limit, rows, bad)

    return check


# One module-level name per check: the code location loads whatever this module exposes.
rate_checks = [_rate_check(limit) for limit in LIMITS]
for _limit, _check in zip(LIMITS, rate_checks, strict=True):
    globals()[_limit.name + "_check"] = _check


def row_count_result(rows: int) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=rows >= MIN_ROWS,
        severity=severity(True),
        description=f"{rows} rows; at least {MIN_ROWS} expected",
        metadata={"rows": dg.MetadataValue.int(rows), "min_rows": dg.MetadataValue.int(MIN_ROWS)},
    )


@dg.asset_check(asset="stg_trips", name="row_count_floor", partitions_def=trip_months, blocking=True,
                description=f"A month has at least {MIN_ROWS:,} rows (real months: 2.96M-3.58M).")
def row_count_floor(context: dg.AssetCheckExecutionContext, redshift: RedshiftData) -> dg.AssetCheckResult:
    month = check_month(context.partition_key)
    rows = redshift.scalar(f"select count(*) from {TABLE} where trip_month = '{month}'")
    return row_count_result(int(rows or 0))


def duplicates_result(rows: int, duplicates: int) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=duplicates <= MAX_DUPLICATES,
        severity=severity(True),
        description=f"{duplicates} exact duplicate row(s) of {rows}; at most {MAX_DUPLICATES} allowed",
        metadata={"rows": dg.MetadataValue.int(rows), "duplicates": dg.MetadataValue.int(duplicates),
                  "max_duplicates": dg.MetadataValue.int(MAX_DUPLICATES)},
    )


@dg.asset_check(asset="stg_trips", name="few_duplicates", partitions_def=trip_months, blocking=True,
                description=f"At most {MAX_DUPLICATES} exact duplicate trips in a month (real months: 0 or 1).")
def few_duplicates(context: dg.AssetCheckExecutionContext, redshift: RedshiftData) -> dg.AssetCheckResult:
    month = check_month(context.partition_key)
    row = redshift.query(
        f"select (select count(*) from {TABLE} where trip_month = '{month}') as rows, "
        f"(select count(*) from (select distinct {TRIP_COLUMNS} from {TABLE} where trip_month = '{month}')) as uniq"
    )[0]
    rows, uniq = int(row["rows"]), int(row["uniq"])
    return duplicates_result(rows, rows - uniq)
