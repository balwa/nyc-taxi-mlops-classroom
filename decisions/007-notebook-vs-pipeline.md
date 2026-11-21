# 007: What stays in the notebook and what moves into the pipeline

Stage: S2 · Date: 2026-11-21 · Author: Tanmay Balwa · Drafted by agent: yes

## Choice

**Pipeline (Dagster, runs on every new month without a person):** building the features (`trip_features`), exporting the training set, fitting, evaluating on the holdout, registering the model version with its tags, the blocking gate, and setting the `challenger` alias.

**Notebook (exploration only):** looking at the data, plotting, and trying ideas on a sample. It logs to its own experiment (`trip-duration-notebook`), never registers a model, and never sets an alias.

## Rejected alternative

Training and registering from the notebook, with the pipeline only supplying data. It is faster to iterate, but a registered version would depend on whatever cell state and sample the notebook happened to have, nobody could rerun it, and an alias could be set by hand, bypassing the gate.

## Why

<!-- Student: rewrite in your own words. -->
Anything that decides what serves real requests has to be repeatable, versioned and gated, so it belongs in a pipeline that runs the same way each month and records the window, holdout, git SHA and metrics on the model. Exploration is the opposite: it needs speed, samples and throwaway code, and nothing it does should be able to reach serving. Splitting at "does it change what serves?" keeps the notebook free to experiment. The cost is that an idea proven in the notebook must be rewritten as pipeline code before it counts.

## What would show this was wrong

A notebook result that can't be reproduced in the pipeline (different numbers from the same data); a promoted model whose tags don't explain how it was trained; or the notebook being used to set an alias or register a version.
