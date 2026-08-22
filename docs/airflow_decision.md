# Why Airflow Is Not Used (Yet)

**Decision:** No Airflow, no DAG scheduler, in Phase 2 or earlier.

**Reason:** the application does not yet have anything that needs one.
Ingestion (`scripts/ingest_sources.py`) is a single-shot, single-machine
pipeline over a corpus of 7 files that runs in ~2-3 seconds - one Python
process, no parallel stages, no cross-run dependencies, no retries-with-
backoff requirement. Standing up a scheduler to orchestrate a 2-second
script would be infrastructure for its own sake, which AGENTS.md rule 19
and this phase's own instructions ("avoid unnecessary infrastructure")
both rule out.

**Revisit when any of these become real, not hypothetical:**

- Scheduled (not on-demand) ingestion - the source pack changes on a cadence
  and needs to be re-ingested automatically.
- Multi-stage background pipelines with real dependencies between stages
  (e.g. ingest -> embed -> index -> evaluate, each with different failure
  modes and retry semantics).
- Recurring issue detection jobs (Operations Radar, Phase 6) that need to
  run on a schedule independent of user requests.
- Dependency-heavy backfills - reprocessing historical data through a
  changed pipeline.
- Any production workflow orchestration need that a single scripted
  pipeline genuinely cannot express (retries, alerting, backfill windows,
  cross-team task ownership).

None of these exist yet. When one does, the evaluation should be Airflow
specifically vs. simpler alternatives (a cron job, a queue worker, a
managed scheduler) based on the actual shape of that need - not a default
reach for Airflow because it is the recognizable name.
