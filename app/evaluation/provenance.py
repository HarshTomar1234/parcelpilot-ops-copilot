"""Reproducibility identifiers for MLflow experiment metadata (Phase 2 s17):
"a model score without configuration provenance is not considered a valid
experiment result." Every value here is computed from the actual repo
state at run time, never hand-typed.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def get_code_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=_REPO_ROOT,
            capture_output=True, text=True, check=True, timeout=5,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown"


def _sha256_of_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def get_source_manifest_checksum() -> str:
    return _sha256_of_file(_REPO_ROOT / "data" / "source_manifest.json")


def get_golden_cases_checksum() -> str:
    return _sha256_of_file(_REPO_ROOT / "tests" / "evaluation" / "golden_cases.json")
