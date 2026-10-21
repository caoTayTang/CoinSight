---
name: incident-report
description: Investigations that need a written report: "what went wrong", health checks across several components, anything the user will forward to a team. Use for the report's structure.
---
# Incident report format

Use this structure, in this order. Keep each section short; skip a section only if it would be empty.

1. **Summary**: one or two sentences: what is wrong, since when, impact.
2. **Findings**: a table of observations: component or asset, what was observed, value, tool, observed time.
3. **Likely cause**: labelled as a hypothesis, with the evidence that supports it and what would confirm it.
4. **Next steps**: concrete operator actions, numbered. Read-only checks first, changes last.
5. **Not checked**: evidence that was unavailable or out of scope, so the reader knows the gaps.

Rules: numbers must come from tool results; mark estimates as estimates; UTC times; no speculation presented as fact.

Every figure in the answer comes from a tool result in this conversation. Placeholders in <angle brackets> show
where a tool value goes; never fill them with example or estimated numbers, and say "not checked" instead.
