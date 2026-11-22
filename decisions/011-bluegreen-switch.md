# 011: What triggers the blue-green switch

Stage: S3 · Date: 2026-11-22 · Author: Tanmay Balwa · Drafted by agent: yes

## Choice

CD flips traffic by itself, after the idle colour passes: `deploy/web.sh smoke` (`/version` reports this commit's SHA, `/predict` answers) and ten more `/predict` calls pinned to the idle colour, every one a 200 with a positive duration. After the switch it checks `/version` through the live route. The old colour keeps running, and rolling back is the `rollback` workflow, which waits for approval in `production`.

## Rejected alternative

Switching with no check beyond a successful deploy, which would let a broken colour take traffic. Also a manual approval before every switch: safest, but every push would wait for a click, and the checks above already cover what a person would look at.

## Why

<!-- Student: rewrite in your own words. -->
The idle colour can be tested with real requests before it has any traffic, so the check is cheap and a failure leaves the live colour untouched. The ten-call loop is the agent's choice of "stricter" (ten, all must pass); change it if you want a different bar.

## What would show this was wrong

A bad version that passes these checks and reaches riders (checks too weak: add one that compares answers to the live colour); a good version blocked by a flaky check; or a rollback that takes longer than a deploy.
