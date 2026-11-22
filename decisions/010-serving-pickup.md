# 010: How serving picks up a new champion

Stage: S3 · Date: 2026-11-22 · Author: Tanmay Balwa · Drafted by agent: yes

## Choice

Serving loads `models:/trip-duration@champion` at start-up and moves only when told: the promote workflow moves the alias, then calls `POST /reload` on `serving-champion` (`deploy/web.sh reload champion`). The old model keeps answering until the new one has loaded and warmed up.

## Rejected alternative

Restarting the container after promotion (simplest, but riders get the static-median fallback while it loads), and serving polling the alias itself (no promote step, but it changes serving code outside the contract and the lag isn't bounded).

## Why

<!-- Student: rewrite in your own words. -->
Promotion should be a visible step: the alias moves, serving is told, and the workflow then checks `/predict` returns the promoted version, so a failure shows up in the run. With `/reload` a rider never sees a gap; with a restart, they would see the median quote for the load time. Polling would hide when a change takes effect.

## What would show this was wrong

A `/reload` that leaves serving on the old model while the alias has moved (the promote check would catch it); a reload that spikes latency or memory on the 8 GB-class app host while both models are loaded; or a reload that fails halfway and leaves serving without a model.
