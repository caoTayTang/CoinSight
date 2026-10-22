import json

import pytest

from pipeline.decision.artifacts.store import ArtifactStore
from pipeline.decision.types import ModelType


def test_run_is_immutable_and_test_can_only_be_claimed_once(tmp_path):
    store = ArtifactStore(tmp_path)
    run = store.create_run("BTC", ModelType.XGBOOST, "snapshot-1", 42)
    store.save_json(run, "validation_metrics.json", {"mae": 1})
    store.finalize(run, "accepted", {"snapshot_id": "snapshot-1"})
    store.verify(run)
    store.seal_validation(run)
    store.claim_test(run)

    with pytest.raises(PermissionError, match="already been consumed"):
        store.claim_test(run)


def test_checksum_verification_detects_modified_artifact(tmp_path):
    store = ArtifactStore(tmp_path)
    run = store.create_run("BTC", ModelType.XGBOOST, "snapshot-1", 42)
    path = store.save_json(run, "validation_metrics.json", {"mae": 1})
    store.finalize(run, "accepted", {"snapshot_id": "snapshot-1"})
    path.write_text(json.dumps({"mae": 2}), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        store.verify(run)


def test_completed_run_cannot_be_reopened_for_resume(tmp_path):
    store = ArtifactStore(tmp_path)
    run = store.create_run("BTC", ModelType.GRU, "snapshot-1", 42)
    store.finalize(run, "accepted", {"snapshot_id": "snapshot-1"})

    with pytest.raises(ValueError, match="immutable status"):
        store.prepare_resume(run)
