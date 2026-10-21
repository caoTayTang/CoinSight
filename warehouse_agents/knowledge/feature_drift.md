# Feature drift / PSI / thay đổi phân phối

Use model_health for the closed-hour BTC feature window, cutoff, row count and PSI values. The current reference_profile is frozen in the anomaly model artifact from its training data. It describes the Isolation Forest feature space, not the CatBoost forecast input space.

PSI compares current bin proportions with fixed reference bin proportions. The tool flags PSI >= 0.25 as a heuristic watch threshold. Small samples and correlated hourly rows make this noisy; PSI is not a significance test, probability, or proof of model failure. Report sample size, cutoff, affected features and reference identity. Missing or nonfinite feature rows must be reported as insufficient evidence, never as zero drift.

First inspect warehouse_coverage, warehouse_quality and warehouse_reconciliation to rule out missing candles, duplicates and load problems. Market regime changes can cause drift even with valid data. Isolation Forest unusualness describes individual market observations; distribution drift describes a window of observations.

Current forecast MAE requires immutable predictions made before each target hour and subsequently joined to realized labels. Without a prospective forecast ledger, report performance unavailable. Frozen retrospective MAE is historical evidence only. Never automatically retrain or change a model because PSI exceeds a threshold.
