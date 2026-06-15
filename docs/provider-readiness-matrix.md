# Provider Readiness Matrix

## Scope

This matrix separates:

- **cataloged in settings**
- **adapter present in code**
- **probe route present**
- **live-verified in this pass**

It does **not** treat configuration support as proof of production routing.

## Verified Inputs

- `services/provider_service.py` defines the supported provider catalog
- `providers/factory.py` defines the actual provider class registry
- `api/settings_routes.py` exposes save/test/model listing routes
- live `/api/health` verified `ollama / qwen2.5-coder:3b`

## Matrix

| Provider | Cataloged in settings | Factory adapter present | Settings test route supported | Live-verified in this pass | Notes |
|---|---:|---:|---:|---:|---|
| Lowus Native | yes | yes | indirect / key-free path | no | Internal native provider path, not externally probed here |
| Ollama | yes | yes | yes | yes | Active live runtime on 2026-06-15 |
| OpenAI | yes | yes | yes | no | Adapter present via OpenAI-compatible provider |
| Anthropic | yes | yes | yes | no | Dedicated adapter present |
| Google Gemini | yes | yes | yes | no | Dedicated adapter present; provider hint warns invalid non-Google-style keys are rejected |
| Groq | yes | yes | yes | no | OpenAI-compatible adapter present |
| Cerebras | yes | yes | yes | no | OpenAI-compatible adapter present; default model set to `gpt-oss-120b` |
| SambaNova | yes | yes | yes | no | OpenAI-compatible adapter present; explicit model selection expected |
| Mistral | yes | yes | yes | no | OpenAI-compatible adapter present |
| Perplexity | yes | yes | yes | no | OpenAI-compatible adapter present |
| OpenRouter | yes | yes | yes | no | OpenAI-compatible adapter present |

## What Is Proven

- The backend catalog and adapter registry are broader than the single live Ollama path.
- The account/settings surface is designed to save masked credentials and run per-provider connection probes.
- A user-facing provider garden exists at the API layer.

## What Is Not Proven Here

- that every configured provider is currently reachable from the live server
- that every provider is currently budget-healthy
- that multi-provider fan-out is universally active across all request classes
- that every provider path has been end-to-end smoke-verified in this public pass

## Next Verification Step

The next technical proof should be a redacted provider smoke report showing:

- provider
- key present or not
- probe attempted or not
- probe result
- default model
- routable yes/no

without exposing raw credentials.
