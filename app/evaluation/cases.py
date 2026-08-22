"""EvaluationCase: the one typed representation of a golden case, decoupled
from any evaluation framework. tests/evaluation/golden_cases.json is not
replaced - this just gives every adapter (pytest, DeepEval, future MLflow
runs) the same typed object instead of each parsing the raw JSON itself
(Phase 2 s13). Fields mirror the JSON exactly; nothing here invents an
expected answer that is not already in the file.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

_DEFAULT_PATH = (
    Path(__file__).resolve().parents[2] / "tests" / "evaluation" / "golden_cases.json"
)


class EvaluationCase(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    category: str
    tags: list[str] = []
    role: str | None = None
    account_scope: object = None  # list[str] | "ALL" | None in the source JSON
    question: str = ""
    expected_status: str = ""
    expected_trust: str | None = None
    expected_tools: list[str] = []
    expected_citations: list[str] = []
    expected_conflicts: list[dict] = []
    expected_facts: dict[str, object] = {}
    expected_assumptions_nonempty: bool | None = None
    must_not: list[str] = []
    enforcement_layer: str | None = None
    notes: str | None = None
    fixture: dict | None = None

    @classmethod
    def from_json(cls, raw: dict) -> EvaluationCase:
        return cls(
            case_id=raw["id"],
            category=raw.get("category", ""),
            tags=raw.get("tags", []),
            role=raw.get("role"),
            account_scope=raw.get("account_scope"),
            question=raw.get("question", ""),
            expected_status=raw.get("expected_status", ""),
            expected_trust=raw.get("expected_trust"),
            expected_tools=raw.get("expected_tools", []),
            expected_citations=raw.get("expected_citations", []),
            expected_conflicts=raw.get("expected_conflicts", []),
            expected_facts=raw.get("expected_facts", {}),
            expected_assumptions_nonempty=raw.get("expected_assumptions_nonempty"),
            must_not=raw.get("must_not", []),
            enforcement_layer=raw.get("enforcement_layer"),
            notes=raw.get("notes"),
            fixture=raw.get("fixture"),
        )

    def is_real_query(self) -> bool:
        """False for action-flow placeholders like '[confirm the same
        prepared action_id twice in a row]' - those describe a sequence of
        calls, not a question a retriever or agent should be asked."""
        return bool(self.question) and not self.question.startswith("[")

    def expected_document_sources(self) -> list[str]:
        """Document (SRC-0X) source_ids named in expected_citations, in
        first-seen order. Excludes SRC-07 (structured data, not retrievable
        via search_documents)."""
        seen: list[str] = []
        for citation in self.expected_citations:
            source_id = citation.split(":", 1)[0]
            if source_id.startswith("SRC-0") and source_id != "SRC-07" and source_id not in seen:
                seen.append(source_id)
        return seen


def load_golden_cases(path: Path = _DEFAULT_PATH) -> list[EvaluationCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [EvaluationCase.from_json(c) for c in raw["cases"]]
