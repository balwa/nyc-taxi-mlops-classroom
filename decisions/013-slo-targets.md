# 013: SLO targets

Stage: S5 · Date: 2026-11-22 · Author: Tanmay Balwa · Drafted by agent: yes

## Choice

Two SLOs, both 99.9% over 30 days (error budget 0.1%, about 43 minutes of full outage):
- **Availability:** responses on Traefik's public entrypoint that are not 5xx, out of all responses except 422s. 422s are the rider's mistake and are excluded.
- **Latency:** `/predict` requests answered in 100 ms or less, measured inside the app.

Each pages when its error ratio is above 14.4x the budget (1.44%) over both a 30-minute and a 5-minute window, with at least 10 requests in the 30 minutes. Rules, tests and reasons are in `observability/rules/slo.rules.yaml`, `slo.test.yaml` and `observability/slo.yaml`.

## Rejected alternative

A "model answered" SLO (`source="model"` in `lab_predictions_total`) as one of the two, or availability counted from the app's own `lab_http_requests_total`. The model SLO would have seen serving's outage, which neither chosen SLO does. Counting in the app would not have seen a stopped app, and measuring per Traefik service (`traefik_service_requests_total`) missed it as well: see the break test below.

## Why

<!-- Student: rewrite in your own words. -->
The SLA is 99.5%, so 99.9% leaves room to react before the SLA is at risk. 100 ms is about twice the p99 measured server-side at 50 requests/s (p95 24 ms, p99 55 ms). A 30-minute window with a 5-minute check was chosen to avoid noisy pages. 14.4x is the usual fast-burn rate: about 1% of the month's budget in 30 minutes, and a full outage crosses it in about 26 seconds at 10 requests/s.

The availability source was changed after the first break test. The app's own metrics and Traefik's per-service metrics went silent when the app container was stopped, because Traefik answers 503 itself without counting it against the service, so the error ratio came out NaN and nothing fired. Traefik's entrypoint counts every response riders get.

Evidence from the break test on 2026-11-22 (stopping the live app container under 20 requests/s):
- 17:18:10 break (`docker stop lab-app-app-blue-1`).
- 17:19:36 `PredictAvailabilityFastBurn` firing, about 1 min 26 s later (includes up to 15 s of polling).
- 17:22:30 fix (`docker start`), 17:22:41 `/predict` answers 200 again.
- The alert was still firing at 17:26 and had cleared by 17:42.
- Client side: 5,302 of 12,000 requests got 503.

## What would show this was wrong

- A serving outage that riders feel but neither SLO sees. On 2026-11-22, with `serving-champion` stopped for 2.5 minutes, every request got 200 with the fallback quote and more than half of the answers in the window came from the fallback. Availability and latency both stayed healthy. That is the case for adding a "model answered" SLO.
- A false page from a deploy or a short blip (30 minutes and 14.4x too sensitive), or an outage that took too long to page.
- The latency threshold being wrong: a busy host making a good model look slow at 100 ms, or a slowdown riders notice that stays under 100 ms.
- Nobody being told: the alert fires in Grafana, but there is no contact point or notification policy yet.
