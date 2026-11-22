# Runbook: bring the lab back after a Learner Lab session end

Owner: Tanmay Balwa · Last run: 2026-11-22 (by hand, in the morning) · Time to restore last run: not timed

## When to use it

"The app doesn't answer", or `scripts/health.sh` prints FAIL or WARN lines after the 4-hour session ended or after Start Lab.

## Before you start

- New credentials: Start Lab, then AWS Details, then export `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and `AWS_SESSION_TOKEN` in your terminal. They live nowhere else.
- Your laptop's current public IP must be in `ingress_cidrs` (`infra/live/terraform.tfvars`) if it isn't `0.0.0.0/0`.
- `gh` logged in, for the status workflow.

## Steps

Nothing was broken when this was written, so the rows below are the checks and the fixes for each piece, not a log of failures. The "Took" column stays "not timed" until a real outage is timed.

| # | Check (command) | Healthy looks like | If not: fix (command) | Took | Automated? |
| --- | --- | --- | --- | --- | --- |
| 1 | `scripts/health.sh` (first, read-only) | every line OK, exit 0 | work down the rows below | not timed | no |
| 2 | `aws sts get-caller-identity` | account and session user shown | Start Lab, re-export the credentials | not timed | no |
| 3 | `aws ec2 describe-instances` | `lab-app`, `lab-platform`, `lab-llm` running, same Elastic IPs | Start Lab starts them; wait a few minutes | not timed | by Start Lab |
| 4 | `gh api repos/<repo>/actions/runners` | `lab-app` and `lab-platform` online | `scripts/register-runner.sh app` / `platform` | not timed | no |
| 5 | `aws rds describe-db-instances` | `lab` available | `aws rds start-db-instance --db-instance-identifier lab` | not timed | no |
| 6 | `aws redshift describe-clusters` | `lab` available | `aws redshift resume-cluster --cluster-identifier lab` | not timed | no |
| 7 | `aws sagemaker describe-notebook-instance --notebook-instance-name lab` | InService, only if you need it | `aws sagemaker start-notebook-instance --notebook-instance-name lab` (about 6 min) | not timed | no |
| 8 | Dagster, MLflow and serving after RDS is up | they come back on their own (Docker restart policy) | `gh workflow run platform.yaml` / `serving.yaml` if one does not | not timed | by Docker |
| 9 | `curl -X POST http://<app_public_ip>/predict -H 'Content-Type: application/json' -d '{"pickup_zone_id": 132, "dropoff_zone_id": 230, "pickup_datetime": "2024-03-08T17:05:00"}'` | `"alias": "champion"` | check the app colour with `deploy/web.sh status` on the app host; `gh workflow run rollback.yaml` if the live colour is bad | not timed | no |
| 10 | `gh workflow run status.yaml` | green, RDS and Redshift `available` | read the failing step | not timed | no |

## Done when

- `curl -X POST http://<app_public_ip>/predict ...` answers with `"alias": "champion"`.
- `scripts/health.sh` exits 0.
- The status workflow is green and reports RDS and Redshift `available`.

## What we automated, and what we left as a step

Nothing was automated in S4: see [decisions/012-restore-no-action.md](../decisions/012-restore-no-action.md). Every step here is still a person's, except the hosts (Start Lab) and the containers that restart themselves. Starting RDS and Redshift stays manual because they cost money while running.
