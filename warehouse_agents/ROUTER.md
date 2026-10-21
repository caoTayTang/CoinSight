# Simple LLM failover router

```text
tier 0: Groq GPT-OSS 120B, one slot per key in GROQ_API_KEY (groq#1, groq#2, ...), rotating
tier 1: OpenRouter Gemma 4 Free
tier 2: Bedrock Claude Haiku 4.5 (last resort)

Each LLM call starts at the next slot of the lowest tier.
Failure -> next slot, then the next tier; missing key/cooldown -> skip.
```

The router is now used by both warehouse reasoning agents. It does not change the forecast model or the main app's chat implementation.

## Paste keys and choose models

1. Put keys in the existing **root `.env`** (not in chat or `router.json`); see `.env.example`. Any key variable may hold a list, `GROQ_API_KEY=["gsk_...","gsk_..."]` (or comma-separated), and the router makes one slot per key. Credential guards check every key in a list.
2. Edit **`warehouse_agents/router.json`**. Routes are tried by `tier`, lowest first. With `round_robin`, each LLM call starts at the next slot within a tier, reserved before network I/O so concurrent calls rotate too; `priority` keeps file order. A higher tier is used only when every slot below it fails or cools down. Use a model that supports function/tool calling and that your account can access.
3. Recreate the extension to load keys/config:

```sh
docker compose --env-file .env -f warehouse_agents/compose.yml up -d --build --force-recreate
```

Example entry for another model as a fallback tier:

```json
{"name":"groq-20b","provider":"groq","model":"openai/gpt-oss-20b","api_key_env":"GROQ_API_KEY","tier":1}
```

Round-robin state and cooldown are per agent process and reset on restart; Analyst and Operations have independent rotations. Rotation spreads traffic but does not increase provider/account quotas, guarantee an RPM ceiling, or coordinate aggregate limits across processes. Groq limits apply per account (organization), so several keys on one account share one limit.

You can repeat a provider with another key, another model, or both. Give every entry a unique `name`. Up to 12 entries. These routes are alternatives in your own configured priority order; configure only keys/accounts you are authorized to use.

Bedrock uses the specified AWS region and Converse API. With an API key, it sends bearer auth directly to the official Bedrock runtime endpoint. For standard AWS IAM credentials instead, use `"api_key_env": null` on that Bedrock entry; the AWS SDK resolves credentials, with SDK retries disabled because the router controls attempts.

Groq and OpenRouter use their official OpenAI-compatible chat completion endpoints. No extra provider SDK is required. Tool definitions, tool-call IDs, argument objects and tool-result/error messages are translated between chat-completions and Converse format, allowing a conversation to continue on another provider after a failure.

## Failure policy

- One attempt per eligible route per LLM call, with **all HTTP 4xx/5xx** eligible for failover as requested. Includes 400/401/402/403/404/422/429 and 500/502/503/504. Redirects are not followed; other unsuccessful HTTP statuses also fall through.
- Missing key: skip the entry; never send an unauthenticated provider request.
- Timeout/network failure, malformed response, incomplete response or unusable tool arguments: move to the next entry.
- A failed slot cools down **30 seconds**, or as long as the provider's `Retry-After` asks if longer (capped at one hour). Subsequent requests skip it meanwhile. It is per process; it is not a distributed rate-limit manager.
- **20 seconds per slot**, **60 seconds total** per LLM call in the shipped config. These are configurable within bounded ranges. The overall agent investigation deadline still applies, so not every configured route is guaranteed an attempt before that deadline.
- If every entry is unavailable, fail explicitly with `RouterUnavailable`. No fabricated answer and no infinite retry loop.
- Invalid model/key/schema errors are not automatically repaired. Fallback can restore service, but failed entries still need fixing. No silent model purchase, new account, key generation or revocation occurs.

Successful agent output includes `routing` (selected slot/provider/model, latency, sanitized attempt statuses with cooldowns) and `steps` (per model call: model, fallbacks, tokens, reasoning when the model returns it, and each tool call with input, output and duration). Keys, auth headers and provider response bodies are excluded. Exhausted route summaries are written to sanitized service logs. Token usage covers the successful provider response; failed attempts can still incur provider charges and are not included in those usage totals.

Because failover crosses providers, **the full conversation, tool schemas and tool evidence can be sent to each eligible configured provider**. Configure only providers approved for that data. The router only obtains model output; application tool validation/execution remains outside it, so changing providers does not execute a tool twice.

## Verify

```sh
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python -m pytest tests/warehouse_agents/test_router.py -q
python -m warehouse_agents.check_runtime
```

Automated tests simulate HTTP error codes, missing keys, timeout, malformed output, cooldown, all-routes-down, total deadline and cross-provider tool-history conversion. The full configured rotation is exercised by the live checker; Groq/OpenRouter live acceptance requires your keys. Mocked tests do not establish that an unconfigured external account/model works.

Provider references: [Groq tool calling](https://console.groq.com/docs/tool-use/local-tool-calling), [Groq API](https://console.groq.com/docs/api-reference), [OpenRouter tool calling](https://openrouter.ai/blog/tutorials/tool-calling/).
