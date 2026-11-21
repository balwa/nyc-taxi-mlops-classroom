# 001: Ingress scope for port 80 on the app host

Stage: S0 · Date: 2026-11-21 · Author: Tanmay Balwa · Drafted by agent: yes

## Choice

`ingress_cidrs = ["0.0.0.0/0"]`: anyone may reach Traefik on port 80 of the app host. No other port is open to the internet; there is no SSH, and the other hosts and RDS accept traffic only from our own security groups.

## Rejected alternative

Allow-list of `/32`s (my IP plus the grader's). It exposes far less, but it breaks whenever my IP changes and locks out anyone who needs to reach the app.

## Why

<!-- Student: confirm or rewrite this in your own words. -->
The app serves only a public, unauthenticated quote endpoint, so there is nothing secret behind port 80. Open access means I never lock myself or the grader out when an IP changes. The cost is that the app is exposed to scanners and abuse, and traffic is plain HTTP.

## What would show this was wrong

Unexpected traffic or scanning in Traefik logs or the S5 request metrics; a service behind port 80 that needs authentication; or a cost or availability problem caused by abusive clients. Then narrow the CIDRs or add auth.
