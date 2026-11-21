# 003: Image tag scheme

Stage: S0 · Date: 2026-11-21 · Author: Tanmay Balwa · Drafted by agent: yes

## Choice

Each image is tagged with the full commit SHA it was built from (`ghcr.io/<owner>/<repo>/<image>:<git sha>`). A rollback points `IMAGE_TAG` at the SHA of an earlier known-good commit.

## Rejected alternative

A mutable `latest` tag (or a semver/date tag). `latest` is simple, but it doesn't say what is running and makes rollback ambiguous.

## Why

<!-- Student: confirm or rewrite this in your own words. -->
A SHA is immutable and traceable: `/version` reports `git_sha`, and the tag matches it, so what runs can be tied to one commit. Rollback is an explicit pointer to a previous SHA. The cost is that tags are long and carry no human meaning such as "v2", so I need git history to know which SHA to roll back to.

## What would show this was wrong

A rollback where I can't tell which SHA was last good; images built from a dirty or rebased history so a SHA no longer maps to a reachable commit; or a deploy that pulled a tag that didn't match the running `git_sha`.
