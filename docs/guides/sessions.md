# Explicit bounded sessions

`Session` drives the existing Runtime with an application policy. Each policy call receives
`SessionView`: current accepted state, latest durable observation, the immediately preceding
StepResult, and the count of completed steps in this invocation. It returns either:

- `SessionStep(objective, grants)` to authorize the next bounded operation; or
- `SessionStop(reason)` to stop without another inference or tool call.

The policy is synchronous trusted code, as is the optional `on_step` observer. These callbacks
must not block or perform external actions. Put actions in registered tools so dispatch and
spending remain durable. `prepare_request` retains the existing context-selection contract;
Session does not concatenate prompts, retain a conversation transcript or select feedback.
The caller owns the provider and SQLiteRun lifetimes.

RunLimits are the single execution budget. There is no independent loop-counter allowance,
implicit correction turn, retry or recovery. The policy may request an explicit correction,
but it spends the existing budget. Grants can narrow runtime authority and cannot expand it.
The wall deadline covers the session as well as each operation; synchronous code remains
cooperative and cannot be forcibly interrupted by asyncio.

`SessionTermination` records `stopped`, `budget_exhausted`, `timed_out`, `cancelled` or `failed`.
It is stored as `flynn.session-termination/v1` JSON in the run's existing opaque terminal
outcome. The SQLite control schema does not change. `stopped` means the application requested
termination; it does not mean a domain task succeeded. `completed_steps` counts fully evaluated
steps in this invocation, not model calls, tokens or total historical operations. The usage
and reservation records remain the accounting authority.

On failure or cancellation, Session records the exception type (not potentially sensitive
exception text) and re-raises the original exception. Pending effects remain pending. A
terminal session cannot execute or automatically recover again. An initially unresolved run
is rejected without changing its terminal outcome; the caller must explicitly reconcile it.
A process death can leave no terminal record; never interpret that absence as a clean stop.

Example policy:

```python
def policy(view):
    if view.last_step is None:
        return SessionStep("Measure the permitted object", ("measure",))
    # Application evaluates what the observation means and chooses continuation.
    return SessionStop("Observation delivered to the domain evaluator")
```

Tools, evaluator, run, adapter and request preparation are passed directly to Session, just
as to Runtime. No provider client, filesystem tool, domain acceptance rule or model prompt
is hidden in the SDK's session driver.

An optional `on_rejection(error, view)` policy can return an explicit `SessionStep` or
`SessionStop` after a certified pre-dispatch `ProposalRejected` (argument validation)
or provider-neutral `InferenceRejected` (response contract). Without it, rejection remains
terminal. DeepSeek's `ProviderResponseRejected` implements the neutral contract.
The runtime certifies the stage after recording failure; exceptions with these same types
from tools, guards or notification callbacks do not qualify. The policy may re-raise to
stop. Corrections spend the existing RunLimits and do not increment completed_steps.
There is no automatic retry, grant expansion, or replay of uncertain effects.
