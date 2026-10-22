"""Shared GRU/LSTM training loop with validation-only early stopping."""
from __future__ import annotations

import time
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import numpy as np

from pipeline.decision.config import TrainingConfig
from pipeline.decision.data.dataloader import ForecastDataModule
from pipeline.decision.training.early_stopping import EarlyStopping
from pipeline.decision.training.seed import seed_everything
from pipeline.decision.types import DatasetSplit, TrainingResult


class TorchTrainer:
    def __init__(self, config: TrainingConfig | None = None):
        self.config = config or TrainingConfig()

    def _dependencies(self):
        try:
            import torch
            from torch import nn
        except ImportError as error:
            raise RuntimeError("PyTorch is required to train GRU/LSTM models") from error
        return torch, nn

    @staticmethod
    def _forward_heads(model, features):
        forward_heads = getattr(model, "forward_heads", None)
        if callable(forward_heads):
            return forward_heads(features)
        return model(features), None

    @staticmethod
    def _atomic_torch_save(torch, value, path: Path) -> None:
        """Write a checkpoint without exposing a partially-written target file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        torch.save(value, temporary)
        temporary.replace(path)

    def _save_training_checkpoint(
        self,
        torch,
        path: Path,
        model,
        optimizer,
        train_loader,
        *,
        completed_epoch: int,
        best_state: dict,
        best_epoch: int | None,
        best_validation_mae: float,
        bad_epochs: int,
        history: list[dict[str, float]],
        duration_seconds: float,
    ) -> None:
        generator = getattr(train_loader, "generator", None)
        self._atomic_torch_save(torch, {
            "format_version": 1,
            "completed_epoch": completed_epoch,
            "model_state_dict": model.state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),
            "best_model_state_dict": best_state,
            "best_epoch": best_epoch,
            "best_validation_mae": best_validation_mae,
            "early_stopping_bad_epochs": bad_epochs,
            "history": history,
            "duration_seconds": duration_seconds,
            "training_config": asdict(self.config),
            "torch_rng_state": torch.get_rng_state(),
            "cuda_rng_state_all": (
                torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None
            ),
            "train_loader_generator_state": (
                generator.get_state() if generator is not None else None
            ),
        }, path)

    def _restore_training_checkpoint(
        self, torch, path: Path, model, optimizer, train_loader
    ) -> dict:
        checkpoint = torch.load(
            path, map_location=self.config.device, weights_only=True
        )
        if checkpoint.get("format_version") != 1:
            raise ValueError(f"unsupported training checkpoint format: {path}")
        model.load_state_dict(checkpoint["model_state_dict"])
        optimizer.load_state_dict(checkpoint["optimizer_state_dict"])
        torch.set_rng_state(checkpoint["torch_rng_state"].cpu())
        cuda_rng = checkpoint.get("cuda_rng_state_all")
        if cuda_rng is not None and torch.cuda.is_available():
            torch.cuda.set_rng_state_all(cuda_rng)
        generator = getattr(train_loader, "generator", None)
        generator_state = checkpoint.get("train_loader_generator_state")
        if generator is not None and generator_state is not None:
            generator.set_state(generator_state.cpu())
        return checkpoint

    def _show_batch_progress(
        self,
        phase: str,
        epoch: int,
        total_epochs: int,
        batch: int,
        total_batches: int,
        metric_name: str,
        metric_value: float,
    ) -> None:
        if not self.config.show_progress:
            return
        interval = self.config.progress_every_batches
        if batch != 1 and batch != total_batches and batch % interval != 0:
            return
        end = "\n" if batch == total_batches else "\r"
        print(
            f"[{phase}] epoch {epoch:03d}/{total_epochs:03d} | "
            f"batch {batch:04d}/{total_batches:04d} | "
            f"{metric_name}={metric_value:.8f}",
            end=end,
            flush=True,
        )

    def train_epoch(
        self, model, loader, optimizer, loss_fn, *, epoch: int = 1, total_epochs: int = 1
    ) -> dict[str, float]:
        torch, _ = self._dependencies()
        model.train()
        total = huber_total = direction_total = persistence_total = 0.0
        q10_total = q50_total = q90_total = 0.0
        count = 0
        total_batches = len(loader)
        for batch, (features, target) in enumerate(loader, start=1):
            non_blocking = bool(loader.pin_memory)
            features = features.to(
                self.config.device, dtype=torch.float32, non_blocking=non_blocking
            )
            target = target.to(
                self.config.device, dtype=torch.float32, non_blocking=non_blocking
            )
            optimizer.zero_grad(set_to_none=True)
            if getattr(model, "quantile_output", False):
                quantiles = model.forward_quantiles(features)
                loss, q10, q50, q90, persistence = loss_fn.components(
                    quantiles, target
                )
                q10_total += float(q10.detach()) * len(target)
                q50_total += float(q50.detach()) * len(target)
                q90_total += float(q90.detach()) * len(target)
            else:
                prediction, direction_logits = self._forward_heads(model, features)
                loss, huber, direction, persistence = loss_fn.components(
                    prediction, target, direction_logits
                )
                huber_total += float(huber.detach()) * len(target)
                direction_total += float(direction.detach()) * len(target)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), self.config.gradient_clip_norm)
            optimizer.step()
            total += float(loss.detach()) * len(target)
            persistence_total += float(persistence.detach()) * len(target)
            count += len(target)
            self._show_batch_progress(
                "train", epoch, total_epochs, batch, total_batches,
                "running_total_loss", total / count,
            )
        metrics = {
            "total": total / count,
            "persistence_ranking": persistence_total / count,
        }
        if getattr(model, "quantile_output", False):
            metrics.update({
                "pinball_q10": q10_total / count,
                "pinball_q50": q50_total / count,
                "pinball_q90": q90_total / count,
                "quantile_loss": (q10_total + q50_total + q90_total) / (3 * count),
            })
        else:
            metrics.update({
                "scaled_huber": huber_total / count,
                "direction_bce": direction_total / count,
            })
        return metrics

    def validate_epoch(
        self,
        model,
        loader,
        *,
        target_scale: float = 1.0,
        epoch: int = 1,
        total_epochs: int = 1,
    ) -> dict[str, float]:
        torch, _ = self._dependencies()
        model.eval()
        absolute_error = 0.0
        return_direction_correct = direction_head_correct = count = 0
        covered = interval_width = 0.0
        zero_scaled = (
            0.0
            if loader.dataset.target_scaler is None
            else float(loader.dataset.target_scaler.transform(np.asarray([0.0]))[0])
        )
        total_batches = len(loader)
        with torch.no_grad():
            for batch, (features, target) in enumerate(loader, start=1):
                non_blocking = bool(loader.pin_memory)
                features = features.to(
                    self.config.device, dtype=torch.float32, non_blocking=non_blocking
                )
                target = target.to(
                    self.config.device, dtype=torch.float32, non_blocking=non_blocking
                )
                if getattr(model, "quantile_output", False):
                    quantiles = model.forward_quantiles(features)
                    prediction = quantiles[:, 1:2]
                    direction_logits = None
                    covered += int(
                        ((target >= quantiles[:, :1]) & (target <= quantiles[:, 2:])).sum()
                    )
                    interval_width += float(
                        (quantiles[:, 2:] - quantiles[:, :1]).sum()
                    ) * target_scale
                else:
                    prediction, direction_logits = self._forward_heads(model, features)
                absolute_error += float(torch.abs(prediction - target).sum()) * target_scale
                return_direction_correct += int(
                    (
                        torch.sign(prediction - zero_scaled)
                        == torch.sign(target - zero_scaled)
                    ).sum()
                )
                direction_target = target > zero_scaled
                direction_head_correct += int(
                    (
                        (direction_logits >= 0)
                        == direction_target
                    ).sum()
                    if direction_logits is not None
                    else (
                        torch.sign(prediction - zero_scaled)
                        == torch.sign(target - zero_scaled)
                    ).sum()
                )
                count += target.numel()
                self._show_batch_progress(
                    "validation", epoch, total_epochs, batch, total_batches,
                    "running_mae", absolute_error / count,
                )
        metrics = {
            "mae": absolute_error / count,
            "directional_accuracy": return_direction_correct / count,
        }
        if getattr(model, "quantile_output", False):
            metrics.update({
                "interval_coverage": covered / count,
                "mean_interval_width": interval_width / count,
            })
        else:
            metrics["direction_head_accuracy"] = direction_head_correct / count
        return metrics

    def fit(
        self,
        model,
        data: ForecastDataModule,
        *,
        checkpoint_dir: Path | None = None,
        resume: bool = False,
    ) -> TrainingResult:
        torch, _ = self._dependencies()
        from pipeline.decision.training.losses import (
            DirectionAwareRegressionLoss,
            QuantilePersistenceLoss,
        )
        if self.config.device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError(
                f"training device is {self.config.device!r}, but CUDA is not available; "
                "set TrainingConfig.device='cpu' or fix the NVIDIA/WSL runtime"
            )
        seed_everything(self.config.seed)
        model.to(self.config.device)
        optimizer = torch.optim.AdamW(
            model.parameters(), lr=self.config.learning_rate,
            weight_decay=self.config.weight_decay,
        )
        zero_scaled = (
            0.0
            if data.target_scaler is None
            else float(data.target_scaler.transform(np.asarray([0.0]))[0])
        )
        target_scale = (
            1.0 if data.target_scaler is None else float(data.target_scaler.scale_)
        )
        loss_kwargs = {
            "zero_scaled": zero_scaled,
            "persistence_weight": self.config.persistence_loss_weight,
            "persistence_margin_fraction": self.config.persistence_margin_fraction,
            "minimum_actual_move_scaled": (
                self.config.minimum_actual_move / target_scale
            ),
        }
        loss_fn = (
            QuantilePersistenceLoss(**loss_kwargs)
            if getattr(model, "quantile_output", False)
            else DirectionAwareRegressionLoss(
                direction_weight=self.config.direction_loss_weight,
                **loss_kwargs,
            )
        )
        stopper = EarlyStopping(self.config.patience)
        best_state = None
        best_epoch = None
        history: list[dict[str, float]] = []
        start_epoch = 0
        previous_duration = 0.0
        started = time.perf_counter()
        train_loader = data.dataloader(DatasetSplit.TRAIN, shuffle=True)
        validation_loader = data.dataloader(DatasetSplit.VALIDATION, shuffle=False)
        last_checkpoint = None if checkpoint_dir is None else Path(checkpoint_dir) / "last_checkpoint.pt"
        best_checkpoint = None if checkpoint_dir is None else Path(checkpoint_dir) / "best_checkpoint.pt"
        if resume:
            if last_checkpoint is None or not last_checkpoint.exists():
                raise FileNotFoundError("cannot resume without last_checkpoint.pt")
            checkpoint = self._restore_training_checkpoint(
                torch, last_checkpoint, model, optimizer, train_loader
            )
            start_epoch = int(checkpoint["completed_epoch"]) + 1
            best_epoch = checkpoint.get("best_epoch")
            stopper.best = float(checkpoint["best_validation_mae"])
            stopper.bad_epochs = int(checkpoint["early_stopping_bad_epochs"])
            history = list(checkpoint.get("history", ()))
            previous_duration = float(checkpoint.get("duration_seconds", 0.0))
            best_state = checkpoint["best_model_state_dict"]
            self._atomic_torch_save(torch, {
                "format_version": 1,
                "state_dict": best_state,
                "best_epoch": best_epoch,
                "best_validation_mae": float(stopper.best),
            }, best_checkpoint)
            if self.config.show_progress:
                print(
                    f"[resume] loaded epoch {start_epoch}/{self.config.max_epochs} | "
                    f"best_epoch={None if best_epoch is None else int(best_epoch) + 1} | "
                    f"best_validation_mae={stopper.best:.8f}",
                    flush=True,
                )
        epoch_range = (
            range(start_epoch, self.config.max_epochs)
            if stopper.bad_epochs < stopper.patience else range(0)
        )
        for epoch in epoch_range:
            epoch_number = epoch + 1
            epoch_started = time.perf_counter()
            train_losses = self.train_epoch(
                model, train_loader, optimizer, loss_fn,
                epoch=epoch_number, total_epochs=self.config.max_epochs,
            )
            validation_metrics = self.validate_epoch(
                model, validation_loader,
                target_scale=(
                    1.0 if data.target_scaler is None else data.target_scaler.scale_
                ),
                epoch=epoch_number, total_epochs=self.config.max_epochs,
            )
            validation_mae = validation_metrics["mae"]
            epoch_history = {
                "epoch": float(epoch),
                "train_total_loss": train_losses["total"],
                "train_persistence_ranking": train_losses[
                    "persistence_ranking"
                ],
                "validation_mae": validation_mae,
                "validation_directional_accuracy": validation_metrics[
                    "directional_accuracy"
                ],
            }
            if getattr(model, "quantile_output", False):
                epoch_history.update({
                    "train_quantile_loss": train_losses["quantile_loss"],
                    "train_pinball_q10": train_losses["pinball_q10"],
                    "train_pinball_q50": train_losses["pinball_q50"],
                    "train_pinball_q90": train_losses["pinball_q90"],
                    "validation_interval_coverage": validation_metrics[
                        "interval_coverage"
                    ],
                    "validation_mean_interval_width": validation_metrics[
                        "mean_interval_width"
                    ],
                })
            else:
                epoch_history.update({
                    "train_scaled_huber": train_losses["scaled_huber"],
                    "train_direction_bce": train_losses["direction_bce"],
                    "validation_direction_head_accuracy": validation_metrics[
                        "direction_head_accuracy"
                    ],
                })
            history.append(epoch_history)
            improved = validation_mae < stopper.best - stopper.min_delta
            should_stop = stopper.update(validation_mae)
            if improved:
                best_state = deepcopy(model.state_dict())
                best_epoch = epoch
            elapsed = previous_duration + time.perf_counter() - started
            if last_checkpoint is not None:
                self._save_training_checkpoint(
                    torch,
                    last_checkpoint,
                    model,
                    optimizer,
                    train_loader,
                    completed_epoch=epoch,
                    best_state=best_state,
                    best_epoch=best_epoch,
                    best_validation_mae=float(stopper.best),
                    bad_epochs=stopper.bad_epochs,
                    history=history,
                    duration_seconds=elapsed,
                )
            if improved and best_checkpoint is not None:
                self._atomic_torch_save(torch, {
                    "format_version": 1,
                    "state_dict": best_state,
                    "best_epoch": best_epoch,
                    "best_validation_mae": float(validation_mae),
                }, best_checkpoint)
            if self.config.show_progress:
                if getattr(model, "quantile_output", False):
                    loss_detail = (
                        f"q10={train_losses['pinball_q10']:.8f} | "
                        f"q50={train_losses['pinball_q50']:.8f} | "
                        f"q90={train_losses['pinball_q90']:.8f} | "
                        f"coverage80={validation_metrics['interval_coverage']:.4f} | "
                    )
                else:
                    loss_detail = (
                        f"huber={train_losses['scaled_huber']:.8f} | "
                        f"direction_bce={train_losses['direction_bce']:.8f} | "
                        f"validation_direction_head="
                        f"{validation_metrics['direction_head_accuracy']:.4f} | "
                    )
                print(
                    f"[epoch] {epoch_number:03d}/{self.config.max_epochs:03d} | "
                    f"train_total={train_losses['total']:.8f} | {loss_detail}"
                    f"persistence={train_losses['persistence_ranking']:.8f} | "
                    f"validation_mae={validation_mae:.8f} | "
                    f"validation_direction={validation_metrics['directional_accuracy']:.4f} | "
                    f"best_mae={stopper.best:.8f} | "
                    f"patience={stopper.bad_epochs}/{stopper.patience} | "
                    f"improved={'yes' if improved else 'no'} | "
                    f"seconds={time.perf_counter() - epoch_started:.1f}",
                    flush=True,
                )
            if should_stop:
                if self.config.show_progress:
                    print(
                        f"[early-stopping] stopped after epoch {epoch_number}; "
                        f"best_epoch={int(best_epoch) + 1 if best_epoch is not None else None}",
                        flush=True,
                    )
                break
        if best_state is None:
            raise RuntimeError("training did not produce a valid checkpoint")
        model.load_state_dict(best_state)
        if self.config.show_progress:
            print(
                f"[training] restored best checkpoint from epoch {int(best_epoch) + 1}; "
                f"best_validation_mae={stopper.best:.8f}",
                flush=True,
            )
        return TrainingResult(
            best_epoch=best_epoch,
            best_validation_mae=float(stopper.best),
            history=tuple(history),
            duration_seconds=previous_duration + time.perf_counter() - started,
        )

    def predict(self, model, data: ForecastDataModule, split: DatasetSplit) -> np.ndarray:
        torch, _ = self._dependencies()
        if self.config.device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError(
                f"prediction device is {self.config.device!r}, but CUDA is not available"
            )
        model.to(self.config.device)
        model.eval()
        values = []
        loader = data.dataloader(split, shuffle=False)
        total_batches = len(loader)
        with torch.no_grad():
            for batch, (features, _) in enumerate(loader, start=1):
                prediction = model(features.to(
                    self.config.device,
                    dtype=torch.float32,
                    non_blocking=bool(loader.pin_memory),
                ))
                values.append(prediction.detach().cpu().numpy().reshape(-1))
                if self.config.show_progress and (
                    batch == 1
                    or batch == total_batches
                    or batch % self.config.progress_every_batches == 0
                ):
                    end = "\n" if batch == total_batches else "\r"
                    print(
                        f"[predict] split={DatasetSplit(split).value} | "
                        f"batch {batch:04d}/{total_batches:04d}",
                        end=end,
                        flush=True,
                    )
        result = np.concatenate(values) if values else np.empty(0, dtype=np.float32)
        if data.target_scaler is not None:
            result = data.target_scaler.inverse_transform(result)
        if not np.isfinite(result).all():
            raise ValueError("model produced NaN or infinite predictions")
        return result

    def predict_direction_probabilities(
        self, model, data: ForecastDataModule, split: DatasetSplit
    ) -> np.ndarray:
        """Return P(UP) from the auxiliary direction head in sample order."""
        torch, _ = self._dependencies()
        if self.config.device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError(
                f"prediction device is {self.config.device!r}, but CUDA is not available"
            )
        if not getattr(model, "separate_direction_head", False):
            raise ValueError("model does not have a separate direction head")
        model.to(self.config.device)
        model.eval()
        values = []
        loader = data.dataloader(split, shuffle=False)
        with torch.no_grad():
            for features, _ in loader:
                _, direction_logits = self._forward_heads(model, features.to(
                    self.config.device,
                    dtype=torch.float32,
                    non_blocking=bool(loader.pin_memory),
                ))
                if direction_logits is None:
                    raise ValueError("model did not return direction logits")
                values.append(
                    torch.sigmoid(direction_logits).detach().cpu().numpy().reshape(-1)
                )
        result = np.concatenate(values) if values else np.empty(0, dtype=np.float32)
        if not np.isfinite(result).all():
            raise ValueError("direction head produced NaN or infinite probabilities")
        return result

    def predict_quantiles(
        self, model, data: ForecastDataModule, split: DatasetSplit
    ) -> np.ndarray:
        """Return raw-return q10/q50/q90 in canonical sample order."""
        torch, _ = self._dependencies()
        if not getattr(model, "quantile_output", False):
            raise ValueError("model does not have quantile output")
        if self.config.device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError(
                f"prediction device is {self.config.device!r}, but CUDA is not available"
            )
        model.to(self.config.device)
        model.eval()
        values = []
        loader = data.dataloader(split, shuffle=False)
        with torch.no_grad():
            for features, _ in loader:
                prediction = model.forward_quantiles(features.to(
                    self.config.device,
                    dtype=torch.float32,
                    non_blocking=bool(loader.pin_memory),
                ))
                values.append(prediction.detach().cpu().numpy())
        result = (
            np.concatenate(values, axis=0)
            if values else np.empty((0, 3), dtype=np.float32)
        )
        if data.target_scaler is not None and len(result):
            result = np.column_stack([
                data.target_scaler.inverse_transform(result[:, index])
                for index in range(3)
            ])
        if not np.isfinite(result).all():
            raise ValueError("quantile head produced NaN or infinite predictions")
        if len(result) and not (
            (result[:, 0] <= result[:, 1]) & (result[:, 1] <= result[:, 2])
        ).all():
            raise ValueError("quantile predictions crossed")
        return result
