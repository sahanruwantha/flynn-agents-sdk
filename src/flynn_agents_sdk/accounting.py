"""Derived usage projections. Unknown invocations never silently become free calls."""

import json
from typing import Any

from flynn_agents_sdk.contracts import ContractError, InferenceUsage, UsageStatus


def summarize_usage(records: dict[str, list[dict[str, Any]]]) -> dict[str, int | bool]:
    operations = {row["id"] for row in records["operations"]}
    reports: dict[str, InferenceUsage] = {}
    for row in records["inference_usage"]:
        identity = row["operation_id"]
        if identity not in operations or identity in reports:
            raise ContractError("Usage report must bind exactly one existing operation")
        payload = json.loads(row["payload"])
        reports[identity] = InferenceUsage(**(payload | {"status": UsageStatus(payload["status"])}))
    unknown = sum(report.status == UsageStatus.UNKNOWN for report in reports.values())
    unreported = len(operations - reports.keys())
    return {
        "invocations": len(operations),
        "model_requests": sum(report.request_started for report in reports.values()),
        "scripted_invocations": sum(report.kind == "scripted" for report in reports.values()),
        "unknown_usage_invocations": unknown,
        "unreported_invocations": unreported,
        "known_input_tokens": sum(report.input_tokens or 0 for report in reports.values()),
        "known_output_tokens": sum(report.output_tokens or 0 for report in reports.values()),
        "usage_complete": unknown == 0 and unreported == 0,
    }
