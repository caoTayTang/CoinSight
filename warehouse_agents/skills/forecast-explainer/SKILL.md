---
name: forecast-explainer
description: Explains the BTC next-hour forecast in plain words, how big the predicted move is, and how far to trust it. Use when the user asks what the forecast or prediction says, why it says up or down, whether to trust it, or how the model works.
---

# Forecast explainer

The reader is usually not a data scientist. They want: up or down, by how much, to what price, and can I trust it.

## What `predict_hourly` returns

| Field | Use it as |
|---|---|
| `target_open`, `target_close` | The hour being predicted |
| `reference_close_usdt` | The price now (last closed hour) |
| `predicted_close_usdt` | The expected price at the end of the target hour |
| `expected_move_pct`, `expected_move_usdt` | The move in percent and in USDT; use these, already computed |
| `predicted_log_return` | Internal; never show it |
| `direction` | up, down or flat |
| `target_already_started` | True: the hour has begun, so the forecast is late for acting on |
| `research_test.directional_accuracy_pct` | How often the direction was right in the past test |
| `research_test.relative_mae` | Internal. Near 1 means "about as good as guessing no change" |

## How to say trust

| Evidence | Plain words |
|---|---|
| `model_health` live `relative_mae` below 1 and `reliable` | "On recent hours it has done a bit better than guessing no change" |
| Live `relative_mae` near or above 1 | "On recent hours it has done no better than guessing no change" |
| No live data, or `reliable` false | "Too few recent hours to judge; in past testing it was barely better than guessing no change" |
| `directional_accuracy_pct` near 50 | "It gets the direction right about half the time, close to a coin flip" |

## Workflow

```
- [ ] predict_hourly and model_health together in one step.
```

## Answer

The app draws a "current vs predicted price" chart under the answer. Keep the text to this:

```markdown
**BTC: expected to <rise/fall> about <expected_move_pct>% to <predicted_close_usdt> USDT by <target_close time> UTC.**

| Now | Expected | Direction right in past tests |
|---|---|---|
| <reference_close_usdt> USDT | <predicted_close_usdt> USDT | <directional_accuracy_pct>% of hours |

Low confidence: <one plain trust sentence from the table above>.
```

Add one line "This hour has already started" only if `target_already_started` is true. Nothing else unless asked.

## Gotchas

- Never show `predicted_log_return`, `relative_mae`, PSI or model IDs unless the user asks for technical detail.
- Not a probability, not advice. Don't list limitations one by one; the single "Low confidence" line covers it.
- Round the percent to two decimals and prices to whole USDT.
- Write everything in the user's language, table headers included.
- Say anything about recent accuracy only from a `model_health` result in this conversation. Without one, write
  "recent accuracy not checked".

Every figure in the answer comes from a tool result in this conversation. Placeholders in <angle brackets> show where a tool value goes; never fill them with example or estimated numbers, and say "not checked" instead.
