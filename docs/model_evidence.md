# Models & evidence

**A local research system with trained models, read-only agents and traceable evidence.** This page puts the model results and engineering effort in one place. Figures below are frozen research results, not live monitoring. Updated 20 October 2026.

## What actually runs

| Component | Model / method | What it produces | Evidence boundary |
| --- | --- | --- | --- |
| BTC hourly forecast | Frozen ensemble of two CatBoost models; BTC-only and BTC + ETH features | Next-hour log return and implied close price | A numerical estimate, not a probability or proven trading edge |
| Market anomaly | Trained Isolation Forest, compared with a fixed MAD baseline | Unusualness score for the latest closed BTC candle | No labeled anomaly accuracy, precision or recall |
| Trade / SRE agents | LangGraph with provider/model failover and allowlisted tools | Market and operational investigations with tool evidence | Bounded, on request; no trading, restart or warehouse writes |
| SRE retrieval | Local BM25 over five allowlisted runbooks; neural alternatives benchmarked separately | Source passages, citation IDs and document hashes | Procedural guidance; live status requires live tools |

The daily direction model in the Market Signal view is a separate task. Its probability and evaluation must not be confused with the hourly return forecast.

## Forecast: effort and result

Research included **28 initial recipes, 50 Optuna trials**, feature and history experiments, taker data, cross-asset comparisons, and later calibration/ensemble work. The detailed report contains **536 scored comparison rows**; these are not 536 independent held-out experiments. Repeated selection on the same period makes the best development result optimistic.

| Evaluation | Hours | Relative MAE vs zero-return | MAE reduction | How to interpret it |
| --- | ---: | ---: | ---: | --- |
| Best selected ensemble, July–December 2025 | 4,416 | **0.992930** | **0.7070%** | Development/selection result; the period was reused |
| Same frozen ensemble, January–18 October 2026 | 6,984 | **0.997017** | **0.2983%** | Retrospective test; no refit for this evaluation, but 2026 had been viewed previously |

For the 2026 test, return MAE was **0.00293272** against **0.00294150** for zero-return. Direction accuracy was **52.96%** and balanced accuracy **52.98%**. RMSE was **0.00455452**, slightly worse than the zero-return RMSE **0.00454400**. A small MAE improvement does not establish profit after fees or stable predictive value.

The original 0.95 target was **not achieved**. The saved results show a small signal and a difficult noisy target. More tuning alone is not supported as a reliable route to a 5% improvement.

The serving export was checked against all **6,984 saved 2026 forecasts**. Maximum absolute log-return difference was about **1.71 × 10⁻¹⁵**. This verifies serving equivalence, not future accuracy.

[Open the detailed comparison report](/reports/hourly-research-summary.html) · [Training and backtest](hourly_backtest.md) · [Forecast contract](hourly_forecast_contract.md)

## Anomaly: trained, with honest limits

Isolation Forest uses **256 trees and 10 causal features**, trained on **17,375 rows from 2023–2024**. Its alert threshold was calibrated on **8,760 rows in 2025** and frozen before this test run.

| Same retrospective 2026 timestamps | Flagged hours | Alert rate |
| --- | ---: | ---: |
| Isolation Forest | 78 / 6,984 | 1.1168% |
| MAD baseline | 101 / 6,984 | 1.4462% |

Fewer alerts do not establish a better detector. There are no independently labeled anomaly outcomes. PSI drift checks compare distributions in the **Isolation Forest feature space**, not every CatBoost input; PSI is not current forecast MAE.

## SRE and RAG: what the evidence supports

Runbook retrieval is bounded to reviewed local files. Responses carry source passages, exact citation IDs and SHA-256 document hashes. The Desk lets you open retrieved passages from citations. Citation matching verifies the source ID was returned; it does not prove that every sentence is supported.

BM25, dense, hybrid and reranked retrieval all scored Recall@3 and MRR@3 of 1.0 on **nine positive English smoke questions**. Those author-created questions were visible during development. This checks plumbing on a tiny corpus, not general retrieval quality, Vietnamese performance or answer faithfulness. **BM25 remains the default serving mode.**

The optional fine-tuning pipeline has not trained an adapter. Its tiny seed dataset checks format and evaluation wiring only. Changing the reasoning LLM does not retrain CatBoost or Isolation Forest.

[SRE retrieval and drift](sre_rag.md) · [Router and failover](model_router.md) · [Response guardrails](response_guardrails.md)

## Engineering delivered and readiness

The implementation includes separate local MCP/A2A services, frozen model checksums, closed-candle validation, read-only tool permissions, bounded tool calls and timeouts, provider failover, warehouse evidence queries, and OpenTelemetry traces across delegation and retrieval. Work happens on request; a 30-day always-on laptop run is not required.

**Suitable scope today: supervised local research and demonstration.** Tests and smoke checks provide evidence for specific paths; they do not certify an unattended production service.

Before claiming unattended production readiness, demonstrate:

- End-to-end fault recovery and alerts for data gaps, stale inputs, failed tasks and provider exhaustion, with measured service objectives.
- Durable audit/task recovery, model-artifact backup and a tested restore/rollback procedure.
- TLS, user identity and authorization if the service is exposed beyond trusted localhost; the current shared local token is not multi-user authorization.
- Independent RAG questions with reviewed retrieval relevance, citation support and abstention behavior.
- A prospective prediction/realization ledger if claiming current forecast performance. Drift cannot substitute for this.

[Current system map](current_progress.md) · [Readiness and remaining work](product_readiness.md) · [How to operate the agents](agent_control.md)
