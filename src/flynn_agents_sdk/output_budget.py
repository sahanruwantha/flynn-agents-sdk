"""Derive output admission from immutable reservations and observed usage."""

import json
from typing import Any

from flynn_agents_sdk.contracts import InferenceUsage, OutputBudget, OutputReservation, UsageStatus


def output_budget(records: dict[str, list[dict[str, Any]]]) -> OutputBudget:
    limit = json.loads(records["run"][0]["limits"]).get("output_tokens")
    if limit is None:
        return OutputBudget(None, None)
    reports = {
        row["operation_id"]: json.loads(row["payload"]) for row in records["inference_usage"]
    }
    spent = held = unresolved = breached = 0
    for row in records["output_reservations"]:
        reservation = OutputReservation(row["kind"], row["tokens"])
        raw = reports.get(row["operation_id"])
        usage = (
            None
            if raw is None
            else InferenceUsage(**(raw | {"status": UsageStatus(raw["status"])}))
        )
        if usage is not None and usage.kind != reservation.kind:
            breached += 1
            held += reservation.tokens
            spent += usage.output_tokens or 0
        elif reservation.kind == "scripted":
            continue
        elif usage is None or usage.output_tokens is None:
            held += reservation.tokens
            unresolved += 1
        else:
            spent += usage.output_tokens
            breached += usage.output_tokens > reservation.tokens
    return OutputBudget(limit, max(0, limit - spent - held), spent, held, unresolved, breached)
