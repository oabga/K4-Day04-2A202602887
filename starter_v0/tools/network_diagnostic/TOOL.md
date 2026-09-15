---
name: network_diagnostic
track: bonus
kind: local_status
provider: deterministic_metric_analyzer
requires_env: []
inputs: [latency_ms, packet_loss_percent, dns_resolved]
outputs: [metrics, status, findings, recommendation]
side_effect: false
---
# network_diagnostic

Classifies user-supplied or mock latency, packet-loss, and DNS measurements.
It does not probe a network, inspect an asset, or read the shared-service status page.
Invalid, negative, non-finite, or out-of-range measurements return `invalid_metrics`.
