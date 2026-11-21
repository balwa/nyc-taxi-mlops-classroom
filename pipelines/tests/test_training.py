"""training_set -> trained_model -> eval_report -> beats_champion -> challenger, against the fakes."""

import dagster as dg
import mlflow
import pytest
from fakes import LocalArtifacts, unloading_redshift

from labpipes.contracts import mlflow_contract
from labpipes.defs.training import (
    MAX_P95_MS,
    MIN_IMPROVEMENT,
    beats_champion,
    challenger,
    eval_report,
    gate,
    month_list,
    plan_window,
    train_model,
    trained_model,
    training_set,
    unload_sql,
)
from labpipes.resources import MlflowTracking

NAME = mlflow_contract()["registered_model"]


def test_window_is_the_three_months_before_the_latest():
    assert plan_window(["2024-04", "2024-01", "2024-03", "2024-02"]) == (["2024-01", "2024-02", "2024-03"], "2024-04")
    assert plan_window(["2024-01", "2024-02", "2024-03", "2024-04", "2024-05"])[1] == "2024-05"
    with pytest.raises(ValueError):
        plan_window(["2024-01", "2024-02", "2024-03"])  # nothing left to test on


def test_gate_needs_a_two_percent_improvement_and_the_latency_budget():
    assert (MIN_IMPROVEMENT, MAX_P95_MS) == (0.02, 20.0)
    assert gate(3.9, 4.0, 1.0)[0]  # 2.5% better
    assert gate(3.92, 4.0, 1.0)[0]  # exactly 2% better
    assert not gate(3.93, 4.0, 1.0)[0]  # 1.75% better
    assert not gate(4.1, 4.0, 1.0)[0]
    ok, why = gate(3.0, 4.0, 25.0)
    assert not ok and "p95" in why and "MAE" not in why.split("p95")[0]


def test_unload_sql_doubles_quotes_and_validates_months():
    sql = unload_sql(f"select a from t where trip_month in ({month_list(['2024-01', '2024-02'])})", "s3://b/p/")
    assert sql.startswith("unload ('select a from t where trip_month in (''2024-01'', ''2024-02'')')")
    assert sql.endswith("to 's3://b/p/' iam_role default format as parquet allowoverwrite")
    with pytest.raises(ValueError):
        month_list(["2024-01'; drop table x; --"])


def test_the_gate_blocks_and_the_job_has_the_five_steps():
    (spec,) = beats_champion.check_specs
    assert spec.name == "beats_champion" and spec.blocking and spec.asset_key == dg.AssetKey("eval_report")
    assert train_model.name == "train_model"


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # MLflow's default artifact root is ./mlruns
    resources = {
        "redshift": unloading_redshift(str(tmp_path / "s3")),
        "artifacts": LocalArtifacts(bucket="lab", root=str(tmp_path / "s3")),
        "tracking": MlflowTracking(tracking_uri=f"sqlite:///{tmp_path}/mlflow.db"),
    }
    (tmp_path / "s3" / "lab").mkdir(parents=True)
    return resources


def run(world, **kw):
    return dg.materialize([training_set, trained_model, eval_report, beats_champion, challenger],
                          instance=dg.DagsterInstance.ephemeral(), resources=world, **kw)


def test_first_run_beats_the_baseline_tags_the_version_and_sets_challenger(world):
    result = run(world)
    assert result.success
    client = world["tracking"].client()
    v = client.get_model_version_by_alias(NAME, "challenger")
    assert v.tags.keys() >= set(mlflow_contract()["version_tags"])
    assert v.tags["training_window"] == "2024-01..2024-03" and v.tags["holdout_month"] == "2024-04"
    assert v.tags["features_version"] == "1"
    assert float(v.tags["mae_min"]) < float(v.tags["champion_mae_min"]) * (1 - MIN_IMPROVEMENT)
    metrics = client.get_run(v.run_id).data.metrics
    assert {"mae_min", "p95_latency_ms", "champion_mae_min", "mae_min.manhattan", "mae_min.night"} <= set(metrics)
    ev = result.asset_materializations_for_node("eval_report")[0].metadata
    assert ev["compared_to"].value == "v1 baseline"
    with pytest.raises(mlflow.exceptions.MlflowException):
        client.get_model_version_by_alias(NAME, "champion")  # the pipeline never sets champion


def test_a_version_that_does_not_beat_the_champion_never_becomes_challenger(world):
    assert run(world).success
    client = world["tracking"].client()
    client.set_registered_model_alias(NAME, "champion", "1")  # a person promoted v1
    second = run(world, raise_on_error=False)
    assert not second.success  # the same model can't be 2% better than itself: the blocking check fails
    assert str(client.get_model_version_by_alias(NAME, "challenger").version) == "1"
    assert client.get_model_version(NAME, "2").tags["champion_mae_min"]  # it was still evaluated and tagged
    assert "challenger" not in {e.asset_key.to_user_string() for e in second.get_asset_materialization_events()}
