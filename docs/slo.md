# Reliability objectives (portfolio assumptions)

These are illustrative engineering targets, **not measured SLO achievements**.

- RPC gateway availability objective: **99.9% successful read requests** over 30 days.
- RPC gateway availability SLI: successful read RPC responses / total accepted read RPC requests.
  Application-level JSON-RPC errors can be reported separately.
- RPC health-probe performance objective: **p95 below 2 seconds** over a rolling 30 days.
- At 99.9% availability, a 30-day period permits roughly 43.2 minutes of unsuccessful requests.

The Prometheus alerts provide example thresholds. They are not connected to a paging
system; production would need Alertmanager/PagerDuty and properly evaluated traffic
volume, burn-rate alerts, security and DNS/TLS monitoring.
