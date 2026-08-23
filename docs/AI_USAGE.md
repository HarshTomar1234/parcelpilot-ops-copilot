# AI Tool Usage

Built with **Claude Code** (Anthropic's CLI coding agent), used the way a
senior engineer uses a pairing tool: I set the scope, architecture
constraints, and acceptance criteria for every phase; Claude Code
implemented, tested, and iterated against them under my direction, and I
reviewed every diff before it was committed.

## How it was used

- **Implementation**: the agent pipeline, the deterministic domain layer
  (cancellation/SLA/service-credit rules), the FastAPI + staff UI, and
  the test suites were built phase by phase against specs I wrote, with
  lint/type/test checks run after every change, not batched at the end.
- **Verification, not assumption**: every "done" claim ties to a command
  that was actually run against the real database or a live Docker
  container - not just a unit test in isolation.
- **Live testing**: once I added a real Anthropic API key, I had it
  re-test the entire stack end to end against the live model, and used
  the app myself to catch what still looked wrong.

## Real bugs found by running the system, not by inspection

- A genuine confirm/execute race condition under concurrent load, fixed
  with an atomic compare-and-swap database write instead of a
  check-then-write.
- A Docker container that crashed entirely on a bad startup secret
  instead of degrading gracefully.
- Testing live for the first time: an account's real status field was
  never being surfaced to the model at all, so it fabricated a status
  from an unrelated document. Traced to a citation-building gap and
  fixed at the source, not patched around.
- A citation self-repair step was silently missing the facts it needed
  to actually correct itself, so it refused to answer instead of
  correcting the answer. Traced to an incomplete repair prompt and fixed.

Full technical writeups: [`docs/red_team_report.md`](red_team_report.md),
[`docs/evaluation_report.md`](evaluation_report.md).

## My role

I set scope, architecture, and acceptance criteria for every phase,
reviewed every diff before commit, ran the live testing session myself
with my own API key, and made the final call on what shipped versus
what's recorded as a known limitation.
