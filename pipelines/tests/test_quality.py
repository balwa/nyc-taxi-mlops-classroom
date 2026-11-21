"""The quality checks: limits, blocking flags, and the decisions in decisions/004-quality-checks.md."""

import dagster as dg
import pytest
from fakes import FakeRedshift, fake_redshift

from labpipes.defs import quality
from labpipes.defs.quality import LIMITS, MIN_ROWS, RateLimit, measure_rate, rate_result, row_count_result

BLOCKING = {"no_null_times_or_zones", "pickups_inside_month", "null_group_under_15_percent", "row_count_floor", "few_duplicates"}


def all_checks():
    return quality.rate_checks + [quality.row_count_floor, quality.few_duplicates]


def test_structural_checks_block_and_noisy_ones_warn():
    flags = {spec.name: spec.blocking for c in all_checks() for spec in c.check_specs}
    assert {n for n, b in flags.items() if b} == BLOCKING
    assert len(flags) == len(LIMITS) + 2


def test_limits_are_five_times_the_worst_real_month():
    by = {limit.name: limit for limit in LIMITS}
    assert by["nonpositive_distance"].max_rate == pytest.approx(0.12, abs=0.001)
    assert by["no_null_times_or_zones"].max_rate == 0.0
    assert by["null_group_under_15_percent"].max_rate == 0.15
    assert MIN_ROWS == 1_000_000


def test_rate_over_the_limit_fails_with_the_declared_severity():
    warn = RateLimit("x", "a = 1", 0.1, False, "")
    block = RateLimit("y", "a = 1", 0.1, True, "")
    assert rate_result(warn, 1000, 100).passed
    r = rate_result(warn, 1000, 101)
    assert not r.passed and r.severity == dg.AssetCheckSeverity.WARN
    assert rate_result(block, 1000, 101).severity == dg.AssetCheckSeverity.ERROR


def test_empty_month_has_zero_rate_but_fails_the_floor():
    assert rate_result(LIMITS[0], 0, 0).passed
    assert not row_count_result(0).passed
    assert not row_count_result(MIN_ROWS - 1).passed
    assert row_count_result(MIN_ROWS).passed


def test_real_months_would_pass_the_gates():
    # Jan: 56 negative durations, 18 pickups outside the month, 11.2% null group, 1 duplicate.
    by = {limit.name: limit for limit in LIMITS}
    rows = 2_964_624
    assert rate_result(by["negative_duration"], rows, 56).passed
    assert rate_result(by["pickups_inside_month"], rows, 18).passed
    assert rate_result(by["null_group_under_15_percent"], rows, 140_162).passed
    assert quality.duplicates_result(rows, 1).passed
    assert not quality.duplicates_result(rows, quality.MAX_DUPLICATES + 1).passed


def test_a_corrupt_month_trips_the_gates():
    by = {limit.name: limit for limit in LIMITS}
    rows = 3_000_000
    assert not rate_result(by["null_group_under_15_percent"], rows, rows // 4).passed
    assert not rate_result(by["pickups_inside_month"], rows, 5000).passed
    assert not rate_result(by["no_null_times_or_zones"], rows, 1).passed


class Counting(FakeRedshift):
    def query(self, sql: str) -> list[dict]:
        super().query(sql)
        return [{"rows": 10, "bad": 2}]


def test_measure_rate_validates_the_month_and_formats_the_filter():
    rs = Counting(cluster_id="lab", database="lab", db_user="labadmin")
    fake_redshift()
    assert measure_rate(rs, "2024-03", "trip_distance <= 0") == (10, 2)
    with pytest.raises(ValueError):
        measure_rate(rs, "2024-03'; drop table x; --", "trip_distance <= 0")
