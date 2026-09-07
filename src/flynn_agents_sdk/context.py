"""Deterministic, bounded context selection with explicit omissions and evidence IDs."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextItem:
    id: str
    text: str
    priority: int = 0
    evidence_ids: tuple[str, ...] = ()
    required: bool = False


@dataclass(frozen=True)
class ContextPacket:
    text: str
    included_ids: tuple[str, ...]
    omitted_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]


class ContextCompiler:
    """Select whole items within a character budget; never silently truncate evidence.

    This bounds text characters, not model tokens or image cost. The application
    determines relevance and supplies trusted priorities.
    """

    def __init__(self, *, max_characters: int = 12000) -> None:
        if type(max_characters) is not int or max_characters <= 0:
            raise ValueError("Context character budget must be positive")
        self.max_characters = max_characters

    def compile(self, items: tuple[ContextItem, ...]) -> ContextPacket:
        if len({item.id for item in items}) != len(items):
            raise ValueError("Context item IDs must be unique")
        included: list[str] = []
        omitted: list[str] = []
        evidence: list[str] = []
        parts: list[str] = []
        size = 0
        for item in sorted(items, key=lambda item: (not item.required, -item.priority)):
            part = f"[{item.id}]\n{item.text}"
            cost = len(part) + (2 if parts else 0)
            if size + cost > self.max_characters:
                if item.required:
                    raise ValueError(f"Required context item {item.id!r} exceeds context budget")
                omitted.append(item.id)
                continue
            parts.append(part)
            size += cost
            included.append(item.id)
            evidence.extend(item.evidence_ids)
        return ContextPacket(
            "\n\n".join(parts), tuple(included), tuple(omitted), tuple(dict.fromkeys(evidence))
        )
