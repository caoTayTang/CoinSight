---
name: incident-report
description: Structures a written incident report across warehouse data, services and models, for an operator or a team. Use when the user asks what went wrong, wants a full health check across several components, or asks for something they will forward.
---

# Incident report

## Gather evidence

Call these together in the first step. Skip only what is clearly out of scope.

```
- [ ] service_health
- [ ] warehouse_coverage for BTC, ETH and SOL (window 48 unless the user gave one)
- [ ] warehouse_status
- [ ] warehouse_reconciliation and warehouse_mart_parity
- [ ] warehouse_quality
```

Second step, only for what the first step flagged: `warehouse_lineage` for an asset with gaps, `airflow_status` for a failed batch, or `search_traces` for a failing service. Legacy `model_health` is production-disabled; do not claim current drift evidence.

## Severity

| Level | When |
|---|---|
| High | Data stopped arriving (`last_observed_open` behind), a core service `unreachable`, or `accounting_delta` ≠ 0 |
| Medium | Gaps inside the window, mart/fact mismatch, error-severity check failed, stream stale |
| Low | Warning-severity checks, drift flags, latency only |
| None | Every check ok. Say so, and list what was checked. |

## Report

Use these sections in this order. Skip a section only if it would be empty.

```markdown
## Summary
<Severity>. <What is wrong, since when, what is affected. Two sentences at most.>

## Findings
| Component / asset | Observed | Value | Tool | Observed at (UTC) |
|---|---|---|---|---|

## Likely cause
Hypothesis: <cause>. Supported by <findings>. Would be confirmed by <check>.

## Next steps
1. <read-only check>
2. <change, last>

## Not checked
<tools that were unavailable or skipped, and why>
```

## Gotchas

- One finding per row; every asset with a problem, including ones the user didn't name.
- "Likely cause" is a hypothesis. Never state it as fact.
- Next steps are for an operator. You don't restart, reload or backfill anything.
- No emoji, no preamble, no closing summary. The Summary section is the summary.

Every figure in the answer comes from a tool result in this conversation. Placeholders in <angle brackets> show where a tool value goes; never fill them with example or estimated numbers, and say "not checked" instead.
