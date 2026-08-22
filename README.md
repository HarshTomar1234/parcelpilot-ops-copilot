# ParcelPilot Ops Copilot

An internal support/operations assistant for ParcelPilot staff. It answers
questions by retrieving from the supplied policy/agreement corpus, looking up
scoped operational data, computing outcomes deterministically, citing
evidence, surfacing source conflicts, and requiring confirmation before any
state change.

**Status: Phase 1 complete (data foundation and retrieval).** The agent,
authorization enforcement beyond account scoping, actions, Operations Radar,
and UI are not built yet - see [Roadmap](#roadmap).

## What exists today

- Reproducible ingestion of the six policy/agreement PDFs and the operational
  workbook into a single SQLite database, rebuilt from scratch on every run.
- Page- and section-aware document chunking with full provenance (source,
  page, section, status, authority class, effective date, account scope).
- Structured extraction of the first-response SLA grid and each agreement's
  per-account targets, so `Enterprise / P1 / "30 minutes, 24x7"` stays one
  associated fact instead of three flattened lines of text.
- Deterministic full-text retrieval (SQLite FTS5 + BM25) with metadata
  filtering applied before ranking.
- Typed, authorization-aware structured-data lookups for accounts, orders,
  and tickets - every function takes an `AuthContext` and filters by account
  scope in the query, not after.
- A snapshot clock: every date/time computation uses the workbook's README
  snapshot (`2026-08-16 11:00 Asia/Kolkata`), never the machine clock.
- 64 tests (unit, integration, regression) and a retrieval evaluation report
  against the golden case set.

## Architecture

```
source pack (PDFs + xlsx, external, never committed)
        |
        v
scripts/ingest_sources.py
  - validate files present, verify checksums
  - parse PDFs -> page-aware sections (app/documents/pdf_parser.py)
  - cross-check parsed metadata against data/source_manifest.json
  - extract SLA tables (app/documents/sla_table.py)
  - parse workbook -> typed Account/Order/Ticket (app/structured_data/workbook.py)
        |
        v
  build/parcelpilot.db (SQLite, gitignored, rebuilt from scratch each run)
   - sources, document_chunks (+FTS5), sla_targets
   - accounts, orders, tickets
        |
        +--> app/documents/retrieval.py    search_documents()
        +--> app/structured_data/repository.py   get_*/search_* (AuthContext-scoped)
```

Full rationale for each decision is in
[`docs/architecture_decision_record.md`](docs/architecture_decision_record.md).

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -e ".[dev]"
```

## Source pack

The customer/assessment files are never committed to this repository
(`AGENTS.md` rule 18). Supply your own copy and point tooling at it, either
via `--source-dir` or the `PARCELPILOT_SOURCE_DIR` environment variable
(see `.env.example`). The expected pack is the six PDFs plus
`ParcelPilot_Assessment_Data.xlsx`; SHA256 checksums for all seven are in
`data/source_manifest.json`, and ingestion refuses to run against a pack that
doesn't match them.

## Ingestion

```powershell
.venv\Scripts\python.exe scripts\ingest_sources.py --source-dir "<pack>\source-pack" --db build\parcelpilot.db
```

Fails loudly (typed exceptions in `app/errors.py`) on a missing file, a
checksum mismatch, a parse error, or a workbook row referencing an unknown
account - never skips a bad source and continues.

## Tests

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Tests that need the source pack look for it via `PARCELPILOT_SOURCE_DIR`,
falling back to `../parcelpilot-assessment/source-pack`, and skip (not fail)
if neither is found - a clean checkout without the pack still collects.

- `tests/unit/` - parsing and normalization logic in isolation, no I/O.
- `tests/integration/` - full ingest into a temp database, then query it.
- `tests/regression/` - guards against regressing specific documented traps
  (deprecated policy mislabeled as current, an agreement losing its account
  scope, the snapshot drifting).

## Evaluation

```powershell
.venv\Scripts\python.exe scripts\run_retrieval_eval.py --source-dir "<pack>\source-pack"
```

Runs every applicable case in `tests/evaluation/golden_cases.json` through
`search_documents()` and writes measured Recall@3/@5, source hit rate, and
p50/p95 latency to
[`docs/retrieval_evaluation.md`](docs/retrieval_evaluation.md). Only measured
numbers are reported.

## Configuration

See `.env.example`. `PARCELPILOT_SOURCE_DIR` and `PARCELPILOT_DB_PATH` are
read by Phase 1. The `BUSINESS_*` variables are placeholders for the
business-calendar assumption a future phase's SLA logic will need
([ADR-007](docs/architecture_decision_record.md#adr-007--business-hours-are-configuration-and-business-hour-slas-are-conditional));
nothing in this phase consumes them yet.

## Deployment

Not built yet - Phase 1 has no HTTP surface. See the Roadmap.

## Design decisions

[`docs/architecture_decision_record.md`](docs/architecture_decision_record.md)
covers retrieval strategy (deterministic BM25 first, embeddings only if
measured to help), source-authority precedence, why an agreement can either
override or explicitly decline to override a default rule, and why SLA
compliance is unmeasurable from this workbook (no `first_response_at`
column - only the deadline is computable).

## Limitations

- No agent, no LLM calls, no chat interface yet.
- Authorization is account-scope filtering only; role-based field allowlists
  and action permissions are not implemented.
- Business-hour SLA targets are parsed (`requires_business_calendar`) but not
  evaluated - the pack never defines a business calendar.
- Retrieval is per-chunk BM25 with no cross-source conflict resolution by
  design (`app/documents/retrieval.py` returns evidence; a later policy layer
  decides applicability) - see `docs/retrieval_evaluation.md` for one
  documented ranking sensitivity on artificially sparse queries.
- The SQLite database is single-writer and rebuilt from scratch each run;
  fine at this corpus size, not a concurrency design.

## Development

```powershell
.venv\Scripts\python.exe -m ruff check app scripts tests      # lint
.venv\Scripts\python.exe -m pyright app scripts\ingest_sources.py tests   # typecheck
.venv\Scripts\python.exe -m pytest -q                          # test
.venv\Scripts\python.exe scripts\run_retrieval_eval.py --source-dir "<pack>\source-pack"  # evaluation
```

A `Makefile` wraps the same commands (`make lint`, `make typecheck`, `make
test`, `make eval`, `make check`) for contributors who have `make`.

## AI-assisted development

This phase was built with Claude (Anthropic) via Claude Code, used for
implementation, test writing, and running the verification commands shown
above. Every claim of "done" in this README corresponds to a command in this
README that was actually run.

## Roadmap

Phase 1 data & retrieval (done) -> Phase 2 structured tools & deterministic
business rules -> Phase 3 bounded agent orchestration -> Phase 4
role/field-level authorization -> Phase 5 action confirmation & audit ->
Phase 6 Operations Radar -> Phase 7 evaluation, latency, cost, observability
-> Phase 8 UI -> Phase 9 deployment -> Phase 10 docs & demo.
