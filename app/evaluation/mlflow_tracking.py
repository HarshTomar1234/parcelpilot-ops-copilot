"""Lightweight local MLflow experiment tracking (Phase 2 s16-17).

MLflow answers "what configuration produced this evaluation result?" -
DeepEval/pytest answer "was the behavior good?". This module only records;
it never decides pass/fail. A local file-based tracking store (mlruns/,
gitignored) is enough at this scale - no tracking server is stood up.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.evaluation.provenance import (
    get_code_sha,
    get_golden_cases_checksum,
    get_source_manifest_checksum,
)

# MLflow 3.x deprecated the plain filesystem backend ("file:./mlruns") in
# favor of a database backend - sqlite is still fully local and file-based
# (build/mlflow.db, gitignored), matching "a lightweight local tracking
# configuration is enough for this phase" without fighting the deprecation.
_DEFAULT_TRACKING_URI = "sqlite:///build/mlflow.db"


class ExperimentRun(BaseModel):
    """Every field a later reader needs to reproduce or distrust a result -
    if it isn't here, the run's score is not a reproducible result."""

    model_config = ConfigDict(frozen=True)

    experiment_name: str
    run_name: str | None = None

    code_sha: str
    source_manifest_checksum: str
    evaluation_suite_checksum: str

    provider: str
    model: str
    prompt_version: str | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None

    retrieval_top_k: int | None = None
    retrieval_config: dict[str, object] = {}

    metrics: dict[str, float] = {}
    latency_ms: dict[str, float] = {}
    token_usage: dict[str, int] = {}
    estimated_cost_usd: float | None = None

    tags: dict[str, str] = {}

    @classmethod
    def build(
        cls,
        experiment_name: str,
        provider: str,
        model: str,
        **kwargs: object,
    ) -> ExperimentRun:
        """Fills in the three provenance fields from the actual repo state
        so callers never have to remember to compute them."""
        return cls(
            experiment_name=experiment_name,
            code_sha=get_code_sha(),
            source_manifest_checksum=get_source_manifest_checksum(),
            evaluation_suite_checksum=get_golden_cases_checksum(),
            provider=provider,
            model=model,
            **kwargs,  # type: ignore[arg-type]
        )


def log_experiment_run(run: ExperimentRun, tracking_uri: str = _DEFAULT_TRACKING_URI) -> str:
    """Writes the run to the local MLflow store and returns its run_id."""
    import mlflow

    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(run.experiment_name)

    params: dict[str, object] = {
        "code_sha": run.code_sha,
        "source_manifest_checksum": run.source_manifest_checksum[:12],
        "evaluation_suite_checksum": run.evaluation_suite_checksum[:12],
        "provider": run.provider,
        "model": run.model,
    }
    if run.prompt_version is not None:
        params["prompt_version"] = run.prompt_version
    if run.temperature is not None:
        params["temperature"] = run.temperature
    if run.max_output_tokens is not None:
        params["max_output_tokens"] = run.max_output_tokens
    if run.retrieval_top_k is not None:
        params["retrieval_top_k"] = run.retrieval_top_k
    for key, value in run.retrieval_config.items():
        params[f"retrieval_config.{key}"] = value

    with mlflow.start_run(run_name=run.run_name, tags=run.tags) as active_run:
        mlflow.log_params(params)
        mlflow.log_metrics(run.metrics)
        for key, value in run.latency_ms.items():
            mlflow.log_metric(f"latency_ms.{key}", value)
        for key, value in run.token_usage.items():
            mlflow.log_metric(f"token_usage.{key}", value)
        if run.estimated_cost_usd is not None:
            mlflow.log_metric("estimated_cost_usd", run.estimated_cost_usd)
        return active_run.info.run_id
