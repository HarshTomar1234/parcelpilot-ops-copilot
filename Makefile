.PHONY: ingest test eval lint typecheck check

SOURCE_DIR ?= ../parcelpilot-assessment/source-pack

ingest:
	python scripts/ingest_sources.py --source-dir "$(SOURCE_DIR)" --db build/parcelpilot.db

test:
	pytest -q

eval:
	python scripts/run_retrieval_eval.py --source-dir "$(SOURCE_DIR)"

lint:
	ruff check app scripts tests

typecheck:
	pyright app scripts/ingest_sources.py tests

check: lint typecheck test
