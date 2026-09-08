"""Adapter configuration identity, separate from changing request evidence."""

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Protocol, runtime_checkable

from flynn_agents_sdk.contracts import ContractError, InferenceRequest


@dataclass(frozen=True)
class InferenceConfiguration:
    provider: str
    model: str
    protocol: str
    settings_json: str

    def __post_init__(self) -> None:
        if any(
            not isinstance(v, str) or not v.strip()
            for v in (self.provider, self.model, self.protocol)
        ):
            raise ContractError("Inference configuration requires provider, model and protocol")
        try:
            settings = json.loads(self.settings_json)
            canonical = json.dumps(settings, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ContractError(
                "Inference configuration settings must be a finite JSON object"
            ) from error
        if not isinstance(settings, dict):
            raise ContractError("Inference configuration settings must be a JSON object")
        object.__setattr__(self, "settings_json", canonical)

    @property
    def sha256(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(payload).hexdigest()


@runtime_checkable
class ConfiguredInference(Protocol):
    def configuration(self, request: InferenceRequest) -> InferenceConfiguration:
        """Describe effective settings without dispatch or budget consumption."""
        ...
