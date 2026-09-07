"""Immutable tool observations; content selection and domain acceptance stay external."""

import json
import math
from dataclasses import dataclass
from typing import Literal

from flynn_agents_sdk.contracts import ContractError


@dataclass(frozen=True)
class TextContent:
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise ContractError("Text content requires a string")


@dataclass(frozen=True)
class ImageContent:
    """A harness-selected image reference. Construction performs no file or network I/O."""

    url: str
    detail: Literal["original", "high", "low", "auto"] = "original"

    def __post_init__(self) -> None:
        if not isinstance(self.url, str) or not self.url.strip():
            raise ContractError("Image content requires a nonempty reference")
        if self.detail not in ("original", "high", "low", "auto"):
            raise ContractError("Unsupported image detail")


def _reject_constant(value: str) -> None:
    raise ContractError(f"Nonfinite JSON number: {value}")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ContractError(f"Nonfinite JSON number: {value}")
    return parsed


def parse_json(value: str) -> object:
    """Reject ambiguous or nonfinite payloads before execution or durable publication."""
    if not isinstance(value, str):
        raise ContractError("JSON payload must be text")
    try:
        return json.loads(
            value,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
            object_pairs_hook=_unique_object,
        )
    except (TypeError, ValueError) as exc:
        raise ContractError(f"Invalid JSON payload: {exc}") from exc


@dataclass(frozen=True)
class ToolResult:
    """Execution result, independent of evaluator verdict and proposed state changes.

    Refusal is an intentional tool response. Unhandled exceptions remain failures and
    propagate through Runtime; they are never converted into a successful observation.
    Structured data is immutable JSON text. Large artifacts should remain references.
    """

    content: tuple[TextContent | ImageContent, ...] = ()
    data_json: str | None = None
    status: Literal["ok", "refused"] = "ok"

    def __post_init__(self) -> None:
        if type(self.content) is not tuple or any(
            type(item) not in (TextContent, ImageContent) for item in self.content
        ):
            raise ContractError("Result content requires a tuple of text or image content")
        if self.status not in ("ok", "refused"):
            raise ContractError("Tool result status must be ok or refused")
        if self.data_json is not None:
            if not isinstance(self.data_json, str):
                raise ContractError("Structured result data requires JSON text")
            parse_json(self.data_json)

    def to_json(self) -> str:
        blocks = []
        for item in self.content:
            if isinstance(item, TextContent):
                blocks.append({"type": "text", "text": item.text})
            else:
                blocks.append({"type": "image", "url": item.url, "detail": item.detail})
        return json.dumps(
            {
                "schema": "flynn.tool-result/v1",
                "status": self.status,
                "content": blocks,
                "data_json": self.data_json,
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @classmethod
    def from_json(cls, value: str) -> "ToolResult":
        document = parse_json(value)
        if not isinstance(document, dict) or set(document) != {
            "schema",
            "status",
            "content",
            "data_json",
        }:
            raise ContractError("Tool result requires the exact v1 key set")
        if document["schema"] != "flynn.tool-result/v1":
            raise ContractError("Unsupported tool result schema")
        if not isinstance(document["content"], list):
            raise ContractError("Tool result content must be an array")
        content: list[TextContent | ImageContent] = []
        for block in document["content"]:
            if not isinstance(block, dict):
                raise ContractError("Content block must be an object")
            if block.get("type") == "text" and set(block) == {"type", "text"}:
                content.append(TextContent(block["text"]))
            elif block.get("type") == "image" and set(block) == {"type", "url", "detail"}:
                content.append(ImageContent(block["url"], block["detail"]))
            else:
                raise ContractError("Unsupported content block or key set")
        return cls(tuple(content), document["data_json"], document["status"])
