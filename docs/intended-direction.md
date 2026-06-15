# Intended Direction

This page is intentionally separate from implemented behavior.

## Intended, Not Yet Claimed As Fully Live

### 1. Wider multi-provider fan-out

Intended direction:

- split a request into bounded subtasks
- route those subtasks across multiple providers
- merge the outputs under one governed response

This is **not** claimed here as universally live for every route.

### 2. Broader provider-garden orchestration

Intended direction:

- stronger provider readiness checks
- budget-aware provider selection
- richer adapter coverage
- better per-provider test and probe workflows

### 3. Expanded memory and agent garden wiring

There are more modules in the private tree than are shown here.

The correct production approach is:

1. identify the authoritative live path
2. wire one contract at a time
3. verify it end to end
4. only then promote it

This showcase does not pretend every dormant or partially wired module is live.
