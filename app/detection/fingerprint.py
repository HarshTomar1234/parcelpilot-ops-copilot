"""Deterministic alert IDs (Phase 5 s8). The same underlying evidence,
window config, and rule version must always produce the same alert_id, so
calling the detection engine repeatedly against unchanged data never
creates duplicate alerts - a caller (or a future scheduler) can safely
re-run detection and diff by alert_id.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from app.detection.models import AlertType


def compute_alert_id(
    alert_type: AlertType, time_window: str, rule_version: str, affected_entities: Iterable[str]
) -> str:
    key = "|".join(
        [alert_type.value, time_window, rule_version, ",".join(sorted(set(affected_entities)))]
    )
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return f"ALERT-{digest}"
