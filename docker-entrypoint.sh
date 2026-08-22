#!/bin/sh
# Makes a prebuilt, already-ingested SQLite snapshot available at
# PARCELPILOT_DB_PATH without ever baking the confidential source
# PDFs/XLSX into the image or the repo. Three ways an operator can supply
# one, tried in this order - documented in README.md's Deployment
# section, with the real size caveat below found by actually testing all
# three against this project's ~180KB real-pack database, not assumed:
#
#   1. A file already present at PARCELPILOT_DB_PATH - e.g. a plain
#      `docker run -v host/parcelpilot.db:/app/build/parcelpilot.db`
#      bind mount. No size limit; the simplest option for a VM/Compose
#      deployment. Nothing to do here. Mount it WRITABLE, not `:ro` - the
#      actions table (the escalation audit trail) is a real write path;
#      a read-only mount serves Support Copilot and Operations Radar
#      fine but makes prepare/confirm/execute fail with a database-is-
#      readonly error, found by actually exercising the action workflow
#      against a `:ro` mount during this phase's own testing.
#   2. PARCELPILOT_DB_B64_FILE - path to a mounted file containing the
#      base64-encoded database (e.g. a Kubernetes Secret or CI secret
#      materialized as a file). No practical size limit either, since
#      it's a file, not an inline value - the recommended option when the
#      platform's secret mechanism won't mount an arbitrary binary file
#      directly but will mount a text secret.
#   3. PARCELPILOT_DB_B64 - the base64 content inline as an env var
#      (mirrors .github/workflows/eval.yml's existing source-pack-secret
#      pattern). Kept for small/demo databases only: this project's real
#      ~180KB database base64-encodes to ~235KB, which already exceeds
#      `docker run --env-file`'s per-line token limit in local testing -
#      prefer option 1 or 2 for anything this size or larger.
set -eu

DB_PATH="${PARCELPILOT_DB_PATH:-build/parcelpilot.db}"

if [ ! -f "$DB_PATH" ]; then
  mkdir -p "$(dirname "$DB_PATH")"
  if [ -n "${PARCELPILOT_DB_B64_FILE:-}" ]; then
    base64 -d "$PARCELPILOT_DB_B64_FILE" > "$DB_PATH"
    echo "decoded PARCELPILOT_DB_B64_FILE into $DB_PATH"
  elif [ -n "${PARCELPILOT_DB_B64:-}" ]; then
    echo "$PARCELPILOT_DB_B64" | base64 -d > "$DB_PATH"
    echo "decoded PARCELPILOT_DB_B64 into $DB_PATH"
  fi
fi

exec "$@"
