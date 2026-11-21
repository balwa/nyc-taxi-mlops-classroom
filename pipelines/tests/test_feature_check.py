"""feature_contract: what "matches" means, from contracts/features.yaml."""

from labpipes.contracts import features_contract
from labpipes.defs.feature_check import bad_value_filter, column_problems, expected_columns, feature_contract

C = features_contract()


def good() -> dict[str, str]:
    return dict(expected_columns(C))


def test_the_contract_table_matches_itself():
    assert column_problems(good(), C) == []
    assert good() == {"trip_month": "character", "pickup_zone_id": "integer", "dropoff_zone_id": "integer",
                      "pickup_hour": "smallint", "pickup_dow": "smallint", "duration_min": "double precision"}


def test_a_forbidden_column_is_named_as_such():
    for leak in ("trip_distance", "fare_amount", "payment_type", "dropoff_at"):
        found = column_problems({**good(), leak: "double precision"}, C)
        assert found == [f"column {leak!r} is not in the contract (known only after the trip: never a feature)"]


def test_unknown_missing_and_retyped_columns_are_problems():
    assert any("not in the contract" in p and "never a feature" not in p for p in column_problems({**good(), "weather": "integer"}, C))
    missing = good()
    del missing["pickup_hour"]
    assert column_problems(missing, C) == ["column 'pickup_hour' is missing"]
    assert column_problems({**good(), "pickup_hour": "integer"}, C) == ["column 'pickup_hour' is integer, the contract says smallint"]


def test_value_filter_covers_every_input_range_and_the_exclusive_label_bound():
    f = bad_value_filter(C)
    assert "pickup_zone_id < 1 or pickup_zone_id > 263" in f
    assert "pickup_hour < 0 or pickup_hour > 23" in f
    assert "pickup_dow < 0 or pickup_dow > 6" in f
    assert "duration_min <= 0 or duration_min > 180" in f  # exclusive lower bound
    assert f.count(" is null") == 5


def test_feature_contract_blocks():
    (spec,) = feature_contract.check_specs
    assert spec.name == "feature_contract" and spec.blocking
