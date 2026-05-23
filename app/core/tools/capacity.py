"""
Back-of-the-envelope capacity estimation tool.

Exposed to the LLM via function-calling so the architecture-generation
pass can ground its scaling decisions in concrete numbers (QPS, storage,
bandwidth) rather than hand-waving.

Pure-function, no I/O — safe to call repeatedly.
"""
from typing import Dict, Any

SECONDS_PER_DAY = 86_400
DAYS_PER_YEAR = 365


def estimate_capacity(
    daily_active_users: int,
    ops_per_user_per_day: float,
    avg_payload_kb: float,
    replication_factor: int = 3,
    peak_to_avg_ratio: float = 3.0,
) -> Dict[str, Any]:
    """
    Compute capacity numbers from user-facing scale parameters.

    Args:
        daily_active_users: Daily active users (e.g. 10_000_000 for 10M DAU).
        ops_per_user_per_day: Average write/read operations per user per day.
        avg_payload_kb: Average payload size per operation in kilobytes.
        replication_factor: Storage replication factor (default 3).
        peak_to_avg_ratio: Peak-to-average multiplier for diurnal spikes
            (default 3.0 — standard rule of thumb).

    Returns:
        Dict with computed metrics. All numbers rounded for readability.
    """
    daily_ops = daily_active_users * ops_per_user_per_day
    qps_avg = daily_ops / SECONDS_PER_DAY
    qps_peak = qps_avg * peak_to_avg_ratio

    daily_bytes = daily_ops * avg_payload_kb * 1024.0
    yearly_gb_raw = (daily_bytes * DAYS_PER_YEAR) / (1024.0 ** 3)
    yearly_gb_replicated = yearly_gb_raw * replication_factor

    avg_bandwidth_mbps = (daily_bytes * 8.0) / (SECONDS_PER_DAY * 1_000_000.0)
    peak_bandwidth_mbps = avg_bandwidth_mbps * peak_to_avg_ratio

    return {
        "qps_avg": round(qps_avg, 1),
        "qps_peak": round(qps_peak, 1),
        "yearly_storage_gb_raw": round(yearly_gb_raw, 1),
        "yearly_storage_gb_replicated": round(yearly_gb_replicated, 1),
        "avg_bandwidth_mbps": round(avg_bandwidth_mbps, 2),
        "peak_bandwidth_mbps": round(peak_bandwidth_mbps, 2),
        "replication_factor": replication_factor,
        "peak_to_avg_ratio": peak_to_avg_ratio,
        "_notes": (
            "qps_peak = qps_avg * peak_to_avg_ratio (rule of thumb for diurnal traffic). "
            "Replicated storage assumes synchronous N-way replication. "
            "Bandwidth excludes protocol overhead and TLS expansion (~10-20% real-world tax)."
        ),
    }


CAPACITY_TOOL_SPEC: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "estimate_capacity",
        "description": (
            "Compute back-of-the-envelope capacity numbers (QPS, storage, bandwidth) "
            "from user-facing scale parameters. Call this BEFORE deciding on scaling "
            "strategy, database sharding, or caching when the user provides concrete "
            "DAU / payload / ops numbers."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "daily_active_users": {
                    "type": "integer",
                    "description": "Daily active users (e.g. 10000000 for 10M DAU).",
                    "minimum": 1,
                },
                "ops_per_user_per_day": {
                    "type": "number",
                    "description": (
                        "Average operations (reads + writes) per user per day. "
                        "E.g. a social-feed user might do ~50 ops/day."
                    ),
                    "minimum": 0,
                },
                "avg_payload_kb": {
                    "type": "number",
                    "description": (
                        "Average payload size per operation in kilobytes. "
                        "Tweet ~1 KB, photo ~500 KB, short video ~5000 KB."
                    ),
                    "minimum": 0,
                },
                "replication_factor": {
                    "type": "integer",
                    "description": "Storage replication factor (default 3 for HA).",
                    "default": 3,
                    "minimum": 1,
                },
                "peak_to_avg_ratio": {
                    "type": "number",
                    "description": (
                        "Peak-to-average traffic multiplier (default 3.0 — "
                        "captures diurnal spikes for consumer apps)."
                    ),
                    "default": 3.0,
                    "minimum": 1.0,
                },
            },
            "required": ["daily_active_users", "ops_per_user_per_day", "avg_payload_kb"],
        },
    },
}
