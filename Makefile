.PHONY: ingest test eval deepeval perf lint typecheck check

SOURCE_DIR ?= ../parcelpilot-assessment/source-pack

ingest:
	python scripts/ingest_sources.py --source-dir "$(SOURCE_DIR)" --db build/parcelpilot.db

test:
	pytest -q

eval:
	python scripts/run_retrieval_eval.py --source-dir "$(SOURCE_DIR)"

deepeval:
	python scripts/run_deepeval_baseline.py --source-dir "$(SOURCE_DIR)"

perf:
	python scripts/run_performance_benchmark.py --source-dir "$(SOURCE_DIR)"

lint:
	ruff check app scripts tests

typecheck:
	pyright app scripts/ingest_sources.py scripts/run_retrieval_eval.py scripts/run_deepeval_baseline.py scripts/run_performance_benchmark.py tests

check: lint typecheck test
