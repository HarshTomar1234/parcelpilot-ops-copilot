from app.evaluation.mlflow_tracking import ExperimentRun, log_experiment_run
from app.evaluation.provenance import (
    get_code_sha,
    get_golden_cases_checksum,
    get_source_manifest_checksum,
)


def test_provenance_fields_are_real_repo_state():
    sha = get_code_sha()
    assert sha == "unknown" or len(sha) == 40  # a real git SHA, or explicitly "unknown"
    assert len(get_source_manifest_checksum()) == 64  # sha256 hex
    assert len(get_golden_cases_checksum()) == 64


def test_experiment_run_build_fills_provenance_automatically():
    run = ExperimentRun.build(experiment_name="test-exp", provider="mock", model="mock-model")
    assert run.code_sha
    assert len(run.source_manifest_checksum) == 64
    assert len(run.evaluation_suite_checksum) == 64


def test_log_experiment_run_is_queryable(tmp_path):
    import mlflow

    db_path = tmp_path / "mlflow.db"
    tracking_uri = f"sqlite:///{db_path}"

    run = ExperimentRun.build(
        experiment_name="test-exp",
        provider="mock",
        model="mock-model",
        prompt_version="support_agent_system_v1",
        retrieval_top_k=5,
        retrieval_config={"account_scope": "ALL"},
        metrics={"recall_at_3": 1.0},
        latency_ms={"p50": 0.5},
        token_usage={"input_tokens": 10, "output_tokens": 5},
        estimated_cost_usd=0.0,
    )
    run_id = log_experiment_run(run, tracking_uri=tracking_uri)

    mlflow.set_tracking_uri(tracking_uri)
    fetched = mlflow.get_run(run_id)
    assert fetched.data.params["code_sha"] == run.code_sha
    assert fetched.data.params["prompt_version"] == "support_agent_system_v1"
    assert fetched.data.metrics["recall_at_3"] == 1.0
    assert fetched.data.metrics["latency_ms.p50"] == 0.5
    assert fetched.data.metrics["estimated_cost_usd"] == 0.0
