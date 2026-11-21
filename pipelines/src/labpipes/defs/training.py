"""S2: training_set, trained_model, eval_report, the beats_champion gate and the challenger asset.

- training_set: UNLOAD the window of staging.trip_features, the holdout month and the zone-pair
  distance lookup (from the window only) to the artifact bucket, under training/<run id>/.
- trained_model: fit tripmodel.LightGBMModel (the given v2), log it to MLflow as a pyfunc with
  tripmodel.model_signature() and the tripmodel package bundled, register a version of the model named
  in contracts/mlflow.yaml and tag it with how it was trained.
- eval_report: tripmodel.evaluate the new version and the champion (the v1 baseline, fit on the same
  window, before there is one) on the same holdout; log the metrics on the run and tag the version.
- beats_champion: the blocking gate. challenger sets the alias, and re-checks the gate itself so that
  materializing it alone can't bypass it. The pipeline never moves `champion`.

Decisions: 007 (what lives here), 008 (2% and 20 ms, overall MAE only), 009 (three months train, the
next one tests). The holdout is the latest month in trip_features; the window is the three before it.
"""

import os
from pathlib import Path

import dagster as dg
import mlflow
import pandas as pd

import tripmodel
from tripmodel import BaselineModel, LightGBMModel, evaluate, model_signature

from ..contracts import features_contract, mlflow_contract
from ..partitions import check_month
from ..resources import ArtifactBucket, MlflowTracking, RedshiftData
from ..runs import last_metadata

WINDOW_MONTHS = 3  # decision 009
MIN_IMPROVEMENT = 0.02  # decision 008: relative MAE improvement over what it is compared against
MAX_P95_MS = 20.0  # decision 008: p95 single-row latency budget
FEATURE_COLUMNS = ["pickup_zone_id", "dropoff_zone_id", "pickup_hour", "pickup_dow"]
LABEL = "duration_min"


def plan_window(months: list[str]) -> tuple[list[str], str]:
    """(training months, holdout month): the latest month tests, the WINDOW_MONTHS before it train."""
    months = sorted(check_month(m) for m in months)
    if len(months) < WINDOW_MONTHS + 1:
        raise ValueError(f"need {WINDOW_MONTHS + 1} months in trip_features to train and test, found {months}")
    return months[-WINDOW_MONTHS - 1 : -1], months[-1]


def unload_sql(select: str, uri: str) -> str:
    """An UNLOAD of `select` to `uri` as Parquet, with the quotes inside doubled."""
    return f"unload ('{select.replace(chr(39), chr(39) * 2)}') to '{uri}' iam_role default format as parquet allowoverwrite"


def month_list(months: list[str]) -> str:
    return ", ".join(f"'{check_month(m)}'" for m in months)


def gate(mae: float, comparator_mae: float, p95_ms: float) -> tuple[bool, str]:
    """Decision 008: MAE at least MIN_IMPROVEMENT below the comparator's, and p95 within the budget."""
    needed = comparator_mae * (1 - MIN_IMPROVEMENT)
    problems = []
    if not mae <= needed:
        problems.append(f"MAE {mae:.3f} is not at least {MIN_IMPROVEMENT:.0%} below {comparator_mae:.3f} (needs <= {needed:.3f})")
    if not p95_ms <= MAX_P95_MS:
        problems.append(f"p95 latency {p95_ms:.2f} ms is over the {MAX_P95_MS:g} ms budget")
    return not problems, "; ".join(problems) or f"MAE {mae:.3f} vs {comparator_mae:.3f}, p95 {p95_ms:.2f} ms"


def load_features(artifacts: ArtifactBucket, prefix: str) -> pd.DataFrame:
    df = artifacts.read_parquet(prefix)
    df[FEATURE_COLUMNS] = df[FEATURE_COLUMNS].astype("int64")
    return df


def load_distances(artifacts: ArtifactBucket, prefix: str) -> pd.DataFrame:
    df = artifacts.read_parquet(prefix)
    df[["pickup_zone_id", "dropoff_zone_id"]] = df[["pickup_zone_id", "dropoff_zone_id"]].astype("int64")
    df["est_distance_miles"] = df["est_distance_miles"].astype("float64")
    return df


@dg.asset(deps=["trip_features"], group_name="model", kinds={"redshift", "s3"}, pool="redshift")
def training_set(context: dg.AssetExecutionContext, redshift: RedshiftData, artifacts: ArtifactBucket) -> dg.MaterializeResult:
    table = features_contract()["table"]
    months = [r["trip_month"].strip() for r in redshift.query(f"select distinct trip_month from {table} order by 1")]
    window, holdout = plan_window(months)
    prefix = f"training/{context.run.run_id}/"
    cols = ", ".join([*FEATURE_COLUMNS, LABEL])
    redshift.execute(unload_sql(f"select {cols} from {table} where trip_month in ({month_list(window)})", artifacts.uri(prefix + "train/")))
    redshift.execute(unload_sql(f"select {cols} from {table} where trip_month in ({month_list([holdout])})", artifacts.uri(prefix + "holdout/")))
    # The distance lookup (est_distance_miles) is built from the window only, never the holdout.
    redshift.execute(unload_sql(
        "select pickup_zone_id, dropoff_zone_id, median(trip_distance) as est_distance_miles from staging.stg_trips "
        f"where trip_month in ({month_list(window)}) and duration_min > 0 and duration_min <= 180 and trip_distance > 0 "
        "and pickup_zone_id between 1 and 263 and dropoff_zone_id between 1 and 263 group by 1, 2",
        artifacts.uri(prefix + "distances/"),
    ))
    train_rows = len(load_features(artifacts, prefix + "train/"))
    holdout_rows = len(load_features(artifacts, prefix + "holdout/"))
    return dg.MaterializeResult(metadata={
        "prefix": dg.MetadataValue.text(prefix),
        "training_window": dg.MetadataValue.text(f"{window[0]}..{window[-1]}"),
        "holdout_month": dg.MetadataValue.text(holdout),
        "train_rows": dg.MetadataValue.int(train_rows),
        "holdout_rows": dg.MetadataValue.int(holdout_rows),
    })


@dg.asset(deps=[training_set], group_name="model", kinds={"python", "mlflow"})
def trained_model(context: dg.AssetExecutionContext, artifacts: ArtifactBucket, tracking: MlflowTracking) -> dg.MaterializeResult:
    ts = last_metadata(context.instance, "training_set")
    contract = mlflow_contract()
    model = LightGBMModel().fit(load_features(artifacts, ts["prefix"] + "train/"), load_distances(artifacts, ts["prefix"] + "distances/"))
    tracking.client()  # points MLflow at the server and the contract's experiment
    with mlflow.start_run() as run:
        mlflow.log_params({"model": "lightgbm", "train_rows": ts["train_rows"], "training_window": ts["training_window"]})
        info = mlflow.pyfunc.log_model(
            name="model", python_model=model, signature=model_signature(),
            code_paths=[str(Path(tripmodel.__file__).parent)], registered_model_name=contract["registered_model"],
        )
    version = str(info.registered_model_version)
    client = tracking.client()
    for key, value in {
        "training_window": ts["training_window"],
        "holdout_month": ts["holdout_month"],
        "features_version": str(features_contract()["version"]),
        "git_sha": os.environ.get("GIT_SHA", "unknown"),
    }.items():
        client.set_model_version_tag(contract["registered_model"], version, key, value)
    return dg.MaterializeResult(metadata={
        "version": dg.MetadataValue.text(version),
        "run_id": dg.MetadataValue.text(run.info.run_id),
        "training_window": dg.MetadataValue.text(ts["training_window"]),
        "holdout_month": dg.MetadataValue.text(ts["holdout_month"]),
    })


def champion_version(client, name: str) -> str | None:
    try:
        return str(client.get_model_version_by_alias(name, "champion").version)
    except mlflow.exceptions.MlflowException:
        return None


@dg.asset(deps=[trained_model], group_name="model", kinds={"python", "mlflow"})
def eval_report(
    context: dg.AssetExecutionContext, redshift: RedshiftData, artifacts: ArtifactBucket, tracking: MlflowTracking
) -> dg.MaterializeResult:
    ts = last_metadata(context.instance, "training_set")
    tm = last_metadata(context.instance, "trained_model")
    contract = mlflow_contract()
    name = contract["registered_model"]
    client = tracking.client()
    holdout = load_features(artifacts, ts["prefix"] + "holdout/")
    zones = redshift.query("select location_id, borough from ingest.taxi_zones")
    boroughs = {int(z["location_id"]): z["borough"] for z in zones}

    new = mlflow.pyfunc.load_model(f"models:/{name}/{tm['version']}")
    champion = champion_version(client, name)
    if champion is not None:
        other = mlflow.pyfunc.load_model(f"models:/{name}/{champion}")
        compared_to, other_predict = f"champion v{champion}", other.predict
    else:
        baseline = BaselineModel().fit(load_features(artifacts, ts["prefix"] + "train/"), load_distances(artifacts, ts["prefix"] + "distances/"))
        compared_to, other_predict = "v1 baseline", lambda df: baseline.predict(None, df)
    new_metrics = evaluate(new.predict, holdout, boroughs)
    other_metrics = evaluate(other_predict, holdout, boroughs)

    run_id = tm["run_id"]
    for key, value in new_metrics.items():
        if key != "holdout_rows":
            client.log_metric(run_id, key, value)
    client.log_metric(run_id, "champion_mae_min", other_metrics["mae_min"])
    for key in ("mae_min", "p95_latency_ms"):
        client.set_model_version_tag(name, tm["version"], key, f"{new_metrics[key]:.6g}")
    client.set_model_version_tag(name, tm["version"], "champion_mae_min", f"{other_metrics['mae_min']:.6g}")
    return dg.MaterializeResult(metadata={
        "version": dg.MetadataValue.text(tm["version"]),
        "compared_to": dg.MetadataValue.text(compared_to),
        "mae_min": dg.MetadataValue.float(new_metrics["mae_min"]),
        "champion_mae_min": dg.MetadataValue.float(other_metrics["mae_min"]),
        "p95_latency_ms": dg.MetadataValue.float(new_metrics["p95_latency_ms"]),
        "holdout_rows": dg.MetadataValue.int(int(new_metrics["holdout_rows"])),
        "slices": dg.MetadataValue.json({k: v for k, v in new_metrics.items() if k.startswith("mae_min.")}),
        "champion_slices": dg.MetadataValue.json({k: v for k, v in other_metrics.items() if k.startswith("mae_min.")}),
    })


@dg.asset_check(asset=eval_report, name="beats_champion", blocking=True,
                description="MAE at least 2% below the champion's (or the v1 baseline's), p95 latency within 20 ms (decision 008).")
def beats_champion(context: dg.AssetCheckExecutionContext) -> dg.AssetCheckResult:
    m = last_metadata(context.instance, "eval_report")
    passed, why = gate(m["mae_min"], m["champion_mae_min"], m["p95_latency_ms"])
    return dg.AssetCheckResult(
        passed=passed, severity=dg.AssetCheckSeverity.ERROR, description=f"{m['compared_to']}: {why}",
        metadata={"version": dg.MetadataValue.text(m["version"]), "min_improvement": dg.MetadataValue.float(MIN_IMPROVEMENT),
                  "max_p95_latency_ms": dg.MetadataValue.float(MAX_P95_MS)},
    )


@dg.asset(deps=[eval_report], group_name="model", kinds={"mlflow"})
def challenger(context: dg.AssetExecutionContext, tracking: MlflowTracking) -> dg.MaterializeResult:
    """Set the `challenger` alias on the version eval_report judged, if it passed the gate."""
    tm = last_metadata(context.instance, "trained_model")
    ev = last_metadata(context.instance, "eval_report")
    passed, why = gate(ev["mae_min"], ev["champion_mae_min"], ev["p95_latency_ms"])
    if ev["version"] != tm["version"]:
        raise dg.Failure(f"eval_report judged v{ev['version']} but the latest trained_model is v{tm['version']}")
    if not passed:  # the blocking check stops this in a run; this stops a lone materialization
        raise dg.Failure(f"v{tm['version']} did not pass the gate: {why}")
    name = mlflow_contract()["registered_model"]
    tracking.client().set_registered_model_alias(name, "challenger", tm["version"])
    return dg.MaterializeResult(metadata={"version": dg.MetadataValue.text(tm["version"]), "alias": dg.MetadataValue.text("challenger")})


train_model = dg.define_asset_job(
    "train_model",
    selection=dg.AssetSelection.assets(training_set, trained_model, eval_report, challenger),
    description="Train on the window, evaluate on the holdout, gate, and set the challenger alias.",
)
