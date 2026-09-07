"""In-memory publication for a trusted, single-event-loop process."""

from flynn_agents_sdk.contracts import (
    Candidate,
    ContractError,
    Evaluation,
    State,
    Verdict,
    check_evaluation,
)


class InMemoryStore:
    """Compare and publish without await points; not thread-safe or durable.

    Trusted evaluators and kernel code own publication. This is not a security
    boundary against Python code that can access the store.
    """

    def __init__(self, value: str = "") -> None:
        if not isinstance(value, str):
            raise ContractError("Initial state must be a string")
        self._state = State(0, value)

    def read(self) -> State:
        return self._state

    def commit(self, candidate: Candidate, evaluation: Evaluation) -> State:
        check_evaluation(candidate, evaluation)
        if evaluation.verdict is not Verdict.SATISFIED:
            raise ContractError("Only a satisfied evaluation permits publication")
        if candidate.base != self._state:
            raise ContractError("Stale candidate base; read current state and evaluate new work")
        if not isinstance(candidate.output, str):
            raise ContractError("Candidate output must be a string")
        self._state = State(self._state.revision + 1, candidate.output)
        return self._state
