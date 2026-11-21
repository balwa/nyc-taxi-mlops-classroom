# 002: Runner credentials

Stage: S0 · Date: 2026-11-21 · Author: Tanmay Balwa · Drafted by agent: yes

## Choice

The self-hosted runner (label `lab-app`) uses the host's instance profile (`LabInstanceProfile`) for any AWS access. No AWS keys are stored in GitHub secrets.

## Rejected alternative

Static session credentials in GitHub secrets. They work from any runner, but they expire with each Learner Lab session, need re-uploading every time, and put credentials in a public repo's secrets.

## Why

<!-- Student: confirm or rewrite this in your own words. -->
Instance-profile credentials are temporary and rotate by themselves, and nothing needs refreshing after Start Lab (the S0 brief says so). There is no secret to leak from a public repo. The trade-off is that anything running on the host, including every workflow job, can use the profile's permissions.

## What would show this was wrong

A workflow job using AWS permissions it shouldn't need; a need for AWS access from a GitHub-hosted runner; or a fork-PR job reaching the runner (which `make check` guards against).
