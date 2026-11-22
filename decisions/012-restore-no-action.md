# 012: What to automate after a session end

Stage: S4 · Date: 2026-11-22 · Author: Tanmay Balwa · Drafted by agent: yes

## Choice

No action required. The overnight session end was already dealt with in the morning: the hosts, RDS, Redshift and the notebook were brought back and checked by hand, and the S3 overflow was set up again then. S4 is considered done and no restore automation is added in this stage.

## Rejected alternative

Writing `scripts/restore.sh` or a boot-time unit to bring the lab back after a session end. Not picked, because the restore was already done and verified by hand and there is no new outage to time or learn from today.

## Why

<!-- Student: rewrite in your own words. -->
Nothing was broken when S4 started, so there are no FAIL or WARN rows to put in a runbook, and automation written without a real failure would be a guess about what a machine should do. `scripts/health.sh` shows every piece OK and `/predict` answers with the champion.

## What would show this was wrong

The next session end taking noticeably longer to recover from than it took this morning, or a step that gets forgotten or done in the wrong order. Either would be the reason to write the restore script then.
