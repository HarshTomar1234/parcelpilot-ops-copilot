# ParcelPilot Ops Copilot

An internal support/operations copilot for authorized ParcelPilot staff: it
answers natural-language support questions by retrieving from the supplied
policy/agreement corpus, looking up scoped operational data, computing
outcomes deterministically, citing its evidence, surfacing source conflicts,
and asking for confirmation before it changes anything.

> **Status: Phase 0 complete (forensic source inspection).**
> No application code exists yet. What is committed is the verified
> understanding of the sources that Phase 1+ will be built against.

## Why this shape

The source pack is deliberately imperfect — a deprecated policy, two customer
agreements that override general rules in opposite directions, and two closed
tickets whose recorded resolutions are wrong. The system is therefore built
around a stated order of authority rather than "whatever retrieval returned
first", and it is designed to abstain where the pack is genuinely silent.

See [`docs/architecture_decision_record.md`](docs/architecture_decision_record.md)
for the decisions and their trade-offs.

## Phase 0 documents

| Document | Contents |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Permanent engineering rules for every coding session |
| [`docs/source_inventory.md`](docs/source_inventory.md) | Every source: status, effective date, scope, authority, caveats |
| [`docs/data_dictionary.md`](docs/data_dictionary.md) | Real workbook schema, relationships, data-quality anomalies |
| [`docs/initial_rules.md`](docs/initial_rules.md) | Every verified business rule with citations, conflicts, and gaps |
| [`docs/architecture_decision_record.md`](docs/architecture_decision_record.md) | ADR-001 … ADR-015 |
| [`data/source_manifest.json`](data/source_manifest.json) | Per-source metadata, checksums, parser warnings |
| [`tests/evaluation/golden_cases.json`](tests/evaluation/golden_cases.json) | 32 golden cases derived from the real pack |

## Source pack (not committed)

The customer/assessment files are **never** committed to this repository. To
reproduce the inspection, supply your own copy of the pack and point the
tooling at it:

```powershell
copy .env.example .env      # then set PARCELPILOT_SOURCE_DIR
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe pymupdf openpyxl

.venv\Scripts\python.exe scripts\inspect_sources.py `
    --source-dir "<your pack>\source-pack" --out build\inspection
```

The expected pack is 6 PDFs plus `ParcelPilot_Assessment_Data.xlsx`. SHA256
checksums for all seven are recorded in `data/source_manifest.json`, so a
mismatch is detectable without redistributing the files.

### Verify the documented facts

```powershell
.venv\Scripts\python.exe scripts\inspect_sources.py --self-check `
    --source-dir "<your pack>\source-pack"
```

This asserts every derived number in `docs/initial_rules.md` — cancellation
outcomes, the one eligible service credit, and the SLA deadlines — directly
against the workbook. It fails loudly if the docs and the data ever drift apart.

## Reference time

All dataset reasoning uses the workbook's README snapshot,
**`2026-08-16 11:00 Asia/Kolkata`** — a Sunday — never the machine clock.

## Roadmap

Phase 1 data & retrieval → Phase 2 structured tools & deterministic rules →
Phase 3 bounded agent → Phase 4 authorization → Phase 5 action confirmation &
audit → Phase 6 Operations Radar → Phase 7 evaluation, latency, cost,
observability → Phase 8 UI → Phase 9 deployment → Phase 10 docs & demo.
