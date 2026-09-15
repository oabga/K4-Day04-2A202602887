from __future__ import annotations

import math
from typing import Any


def network_diagnostic(
    latency_ms: float,
    packet_loss_percent: float,
    dns_resolved: bool,
) -> dict[str, Any]:
    """Classify user-supplied network measurements without probing a network."""
    try:
        latency = float(latency_ms)
        packet_loss = float(packet_loss_percent)
    except (TypeError, ValueError):
        return {"tool": "network_diagnostic", "error": "invalid_metrics"}

    if (
        not math.isfinite(latency)
        or not math.isfinite(packet_loss)
        or latency < 0
        or not 0 <= packet_loss <= 100
        or not isinstance(dns_resolved, bool)
    ):
        return {"tool": "network_diagnostic", "error": "invalid_metrics"}

    findings = []
    if not dns_resolved:
        findings.append("dns_resolution_failed")
    if packet_loss > 2:
        findings.append("packet_loss_high")
    if latency >= 100:
        findings.append("latency_high")

    status = "critical" if not dns_resolved or packet_loss >= 10 else "degraded" if findings else "healthy"
    return {
        "tool": "network_diagnostic",
        "metrics": {
            "latency_ms": latency,
            "packet_loss_percent": packet_loss,
            "dns_resolved": dns_resolved,
        },
        "status": status,
        "findings": findings,
        "recommendation": {
            "healthy": "No network action is indicated by these measurements.",
            "degraded": "Check the local link and repeat the measurement.",
            "critical": "Escalate DNS or severe packet-loss troubleshooting.",
        }[status],
    }
