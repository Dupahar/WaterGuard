"""Agent telemetry: one JSON line per inspector decision and per run.

Lines follow the CloudWatch Embedded Metric Format, so when the container logs to CloudWatch
(deploy/user-data.sh) the same line is both a searchable log event and a set of metrics
(namespace WaterGuard/Inspector), with no metrics API calls from the app. Off unless
WATERGUARD_TELEMETRY=1 (the Docker image sets it).
"""
import json
import os
import sys
import time

NAMESPACE = "WaterGuard/Inspector"


def emit(event: str, dims: dict, metrics: dict, **fields):
    """metrics: name -> (value, unit). dims: CloudWatch dimensions (low cardinality only)."""
    if os.getenv("WATERGUARD_TELEMETRY") != "1":
        return
    rec = {"_aws": {"Timestamp": int(time.time() * 1000),
                    "CloudWatchMetrics": [{"Namespace": NAMESPACE, "Dimensions": [list(dims)],
                                           "Metrics": [{"Name": k, "Unit": u} for k, (_, u) in metrics.items()]}]},
           "event": event, **dims, **{k: v for k, (v, _) in metrics.items()}, **fields}
    print(json.dumps(rec, default=str), file=sys.stdout, flush=True)
