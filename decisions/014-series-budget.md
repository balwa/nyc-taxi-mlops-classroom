# 014: Series budget

Stage: S5 · Date: 2026-11-22 · Author: Tanmay Balwa · Drafted by agent: yes

## Choice

Keep the minimum from each source and drop the rest, in `observability/alloy/budget.alloy`:
- **Host:** `up`, CPU idle time, memory total and available, and the `/` filesystem's size and free space. No network, per-device disk or node_exporter bookkeeping.
- **Containers:** CPU usage, working-set memory and last-seen per container. The labels `id`, `image` and every `container_label_*` are dropped, so a redeploy continues the same series.
- **Services:** everything in `contracts/metrics.yaml` and Traefik's per-service series, plus `traefik_entrypoint_requests_total`, the availability SLI's source (added after the first break test: when the app is down Traefik answers 503 itself, and only the entrypoint counts it). Dropped: Traefik's other entrypoint series, and `process_*`, `python_*` and `scrape_*`.

Scrape intervals stay at 15 s and 30 s.

## Rejected alternative

Keeping a larger set: CPU, memory, disk and network for the host, and `container_(cpu|memory|network|spec)` for containers, with only the filesystem series and the changing labels dropped. It would have been about 1,500 to 1,800 series now. It keeps network and spec evidence for an incident, but nothing in the SLOs or the dashboard reads it.

## Why

<!-- Student: rewrite in your own words. -->
With no rules the stack sent 3,483 active series, about half of them from cAdvisor's filesystem and block-I/O metrics. With these rules it sends about 345 (measured in Grafana Cloud: 330 after the rules, 301 to 360 across three deploys in a row, 345 afterwards), about 3% of the 10,000 limit. The minimum was chosen over a larger set because the dashboard and the SLO inputs only use what is kept, and the extra room is there for the LLM host in S6. Dropping `image` means container series no longer say which version ran; `lab_model_info` says which model is loaded.

## What would show this was wrong

An incident where a dropped metric was the one needed (disk full, network saturated, a container's image) and the evidence wasn't there. Or the series count approaching the budget after the LLM host joins, which would mean the app's own label values are growing (the contract says they're bounded). In either case, add back only the metric that was missing.
