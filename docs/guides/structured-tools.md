# Structured observation tools

`Tool.structured` registers an async handler returning `ToolResult`. It uses the ordinary
ToolBroker and Runtime dispatch path: grants, validation, reservations, execution, durable
result and evaluation. It always registers an observation; publishing state requires a
separate explicit state-update operation.

A result carries an immutable tuple of `TextContent` and `ImageContent`, optional immutable
`data_json`, and `ok` or `refused` execution status. Neither status determines domain
acceptance. Exceptions propagate; a dispatched effect without a valid returned result
remains unresolved. Invalid arguments are rejected before handler dispatch.

The harness supplies the JSON object parameter schema and a matching pure validator.
The SDK rejects malformed JSON, duplicate keys, nonfinite numbers and non-object arguments;
it does not infer domain argument constraints from descriptions. Schema interpretation is
not added implicitly. Handlers return native results, not provider or MCP dictionaries.

`ToolResult.to_json()` and `from_json()` preserve the exact structured data text and content
ordering under `flynn.tool-result/v1`. SQLite stores this as the ordinary observation payload;
its control-state schema does not change. Unknown result versions and extra/missing fields
are refused. Image references are inert: the SDK does not fetch them, read files, or put them
into a prompt. The harness selects, resolves and verifies image evidence before sending it
to an adapter. Keep large artifacts outside the journal.

This is the foundation for native tool-driven sessions, not a session runner or a Claude
compatibility API. Tool failure, model termination, evaluation and state commit remain separate.
