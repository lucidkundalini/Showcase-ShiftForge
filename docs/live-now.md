# Live Now

## Scope

This page describes what is **implemented and verified**, not what is merely planned.

## Verified Facts

### 1. Runtime truth answers

ShiftForge has deterministic answer paths for system/runtime questions.

Example verified live identity answer:

> I am ShiftForge: the orchestration layer running this session.
>
> Current runtime: Ollama / qwen2.5-coder:3b / Server / OK.
>
> The model is the current engine. ShiftForge is the runtime that routes requests, uses connected tools and provider paths when permitted, checks claims against available evidence, and says clearly when something is unknown.

### 2. Observability

Each response can carry a trace id and structured diagnostics.

Observed fields include:

- response source
- selected path
- provider
- model
- runtime
- health
- trace id

### 3. MCP/provider introspection

ShiftForge can build a safe, read-only view of:

- registered providers
- configured providers
- enabled user providers
- provider priority
- MCP server names
- tool counts

It does **not** expose raw provider secrets or raw MCP schemas in this public path.

### 4. MCP runtime governance

The backend includes governance behavior that:

- repairs stale internal MCP Python entrypoint paths
- archives invalid generated MCP entries
- blocks dangerous MCP tool calls before execution
- redacts secrets from MCP result payloads

## Verified Live Runtime on 2026-06-15

- provider: `ollama`
- model: `qwen2.5-coder:3b`
- health: `ok`

See:

- [../evidence/health-2026-06-15.json](../evidence/health-2026-06-15.json)
- [../evidence/identity-response-2026-06-15.ndjson](../evidence/identity-response-2026-06-15.ndjson)

## Included Code

### `prompt_metabolism.py`

Shows the runtime-reality scan, knowledge boundary scan, claim validation structures, and deterministic reality answer builder.

### `observability.py`

Shows the trace object, event logging, mutation tracking, and response-release diagnostics.

### `mcp_provider_introspection.py`

Shows safe provider/MCP catalog introspection without live network probing or secret exposure.
