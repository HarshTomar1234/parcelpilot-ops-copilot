# Demo Script (Phase 3)

A short, runnable walkthrough of the agent using
`scripts/run_agent_cli.py`. No frontend exists yet - this is the intended
way to exercise the system today.

## Setup

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -e ".[dev,llm,evaluation]"
.venv\Scripts\python.exe scripts\ingest_sources.py --source-dir "<pack>\source-pack" --db build\parcelpilot.db
```

## 1. A confident, multi-source answer with a resolved conflict

```powershell
.venv\Scripts\python.exe scripts\run_agent_cli.py --question "Can Northstar cancel ORD-1001 without a cancellation fee? Explain why."
```

Expect: `status: completed`, `trust_state: CONFIDENT`, three tools called
(lookup, calculate, search), a `conflicts` section showing the signed
agreement (SRC-05) overriding the standard policy (SRC-03), with the exact
clause cited for both.

## 2. A confidently-answered SLA breach that still gets flagged

```powershell
.venv\Scripts\python.exe scripts\run_agent_cli.py --question "Is TKT-501 within its first-response SLA?"
```

Expect: `status: completed` (not escalated - the calculation is confident,
even though the underlying fact is a P1 breach that should be routed to a
human for operational follow-up).

## 3. Authorization enforced, not just declared

```powershell
.venv\Scripts\python.exe scripts\run_agent_cli.py --question "Can Northstar cancel ORD-1001 without a fee?" --role support_agent --account-scope ACCT-002
```

Expect: the question resolves to a generic informational search, not a
targeted cancellation calculation - ORD-1001 belongs to ACCT-001, outside
this caller's scope, and is silently dropped during entity resolution
rather than producing an authorization error that would confirm it
exists.

## 4. Refusing to fabricate a live result

```powershell
.venv\Scripts\python.exe scripts\run_agent_cli.py --question "test" --live
```

Expect: an immediate, clear refusal (`--live requires ANTHROPIC_API_KEY to
be set; refusing to fabricate a result`) rather than a silent fallback to
a mock answer under a flag that implies a real one.

## 5. Running the test suite live

```powershell
.venv\Scripts\python.exe -m pytest tests/fixture_backed -v
```

Expect: 39 passed, including 9 security regressions and 5 tests proving
the agent generalizes past the real pack's ID conventions - this tier
never needs the real source pack or an API key, and is what
`.github/workflows/ci.yml` runs on every push.

## 6. The evaluation harness, end to end

```powershell
.venv\Scripts\python.exe scripts\run_agent_trajectory_eval.py --source-dir "<pack>\source-pack"
```

Expect: a printed JSON summary (mean tool correctness ~0.89, status match
rate ~0.82) and a written report at
`docs/agent_trajectory_evaluation.md` with a full per-case table.
