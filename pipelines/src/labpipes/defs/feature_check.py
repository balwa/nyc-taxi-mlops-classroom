"""S2: the feature_contract check on trip_features (blocking: contracts/mlflow.yaml).

"Matches" means three things, all read from contracts/features.yaml, with no tolerance because the
contract's ranges are exact:
1. Columns: the table has exactly the keys, inputs and label the contract lists, no more and no fewer.
   A column the contract forbids (anything known only after a trip) is named in the failure.
2. Types: each column has the contract's Redshift type.
3. Values: for the partition's month, every input and the label are non-null and inside their range
   (the label's lower bound is exclusive), and the month has at least one row.
"""

import dagster as dg

from ..contracts import features_contract
from ..partitions import check_month, trip_months
from ..resources import RedshiftData

# information_schema.columns.data_type for the contract's type names.
DATA_TYPES = {"char": "character", "integer": "integer", "smallint": "smallint", "double precision": "double precision"}


def base_type(contract_type: str) -> str:
    """'char(7)' -> 'character', 'double precision' -> 'double precision'."""
    return DATA_TYPES[contract_type.split("(")[0].strip().lower()]


def expected_columns(contract: dict) -> dict[str, str]:
    cols = [*contract["keys"], *contract["inputs"], contract["label"]]
    return {c["name"]: base_type(c["type"]) for c in cols}


def column_problems(actual: dict[str, str], contract: dict) -> list[str]:
    """Differences between the table's columns ({name: data_type}) and the contract."""
    expected = expected_columns(contract)
    problems = []
    for name in sorted(actual.keys() - expected.keys()):
        forbidden = " (known only after the trip: never a feature)" if name in contract["forbidden"] else ""
        problems.append(f"column {name!r} is not in the contract{forbidden}")
    for name in sorted(expected.keys() - actual.keys()):
        problems.append(f"column {name!r} is missing")
    for name in sorted(expected.keys() & actual.keys()):
        if actual[name] != expected[name]:
            problems.append(f"column {name!r} is {actual[name]}, the contract says {expected[name]}")
    return problems


def bad_value_filter(contract: dict) -> str:
    """SQL predicate that is true for a row that breaks a contract range or has a null input or label."""
    parts = []
    for c in [*contract["inputs"], contract["label"]]:
        lo, hi = c["range"]
        low = f"{c['name']} <= {lo}" if c.get("exclusive_min") else f"{c['name']} < {lo}"
        parts.append(f"{c['name']} is null or {low} or {c['name']} > {hi}")
    return " or ".join(parts)


@dg.asset_check(asset="trip_features", name="feature_contract", partitions_def=trip_months, blocking=True,
                description="The table's columns, types and value ranges match contracts/features.yaml.")
def feature_contract(context: dg.AssetCheckExecutionContext, redshift: RedshiftData) -> dg.AssetCheckResult:
    contract = features_contract()
    month = check_month(context.partition_key)
    schema, table = contract["table"].split(".")
    cols = redshift.query(
        "select column_name, data_type from information_schema.columns "
        f"where table_schema = '{schema}' and table_name = '{table}'"
    )
    problems = column_problems({r["column_name"]: r["data_type"] for r in cols}, contract)
    stats = redshift.query(
        f"select count(*) as rows, coalesce(sum(case when {bad_value_filter(contract)} then 1 else 0 end), 0) as bad "
        f"from {contract['table']} where trip_month = '{month}'"
    )[0]
    rows, bad = int(stats["rows"]), int(stats["bad"])
    if not rows:
        problems.append(f"no rows for {month}")
    if bad:
        problems.append(f"{bad} of {rows} rows have a null or an out-of-range value")
    return dg.AssetCheckResult(
        passed=not problems,
        severity=dg.AssetCheckSeverity.ERROR,
        description="matches the contract" if not problems else "; ".join(problems),
        metadata={
            "problems": dg.MetadataValue.json(problems),
            "rows": dg.MetadataValue.int(rows),
            "bad_rows": dg.MetadataValue.int(bad),
            "features_version": dg.MetadataValue.int(int(contract["version"])),
        },
    )
