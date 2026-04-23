"""Questionnaire engine — declarative question bank + branching logic.

Each framework declares a list of :class:`Question` objects. The engine
walks the list, honoring ``condition`` callables that read prior answers
to determine whether a question is visible. Answers are stored as a flat
``dict[str, Any]`` keyed by ``Question.key``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class QuestionOption:
    value: str
    label: str


@dataclass
class Question:
    key: str
    type: str  # single_select | multi_select | number | text | yes_no | date
    label: str
    help_text: str = ""
    options: list[QuestionOption] = field(default_factory=list)
    required: bool = True
    minimum: float | None = None
    maximum: float | None = None
    condition: Callable[[dict[str, Any]], bool] | None = None

    def is_visible(self, answers: dict[str, Any]) -> bool:
        if not self.condition:
            return True
        try:
            return bool(self.condition(answers))
        except Exception:
            # A broken condition should not crash the wizard — skip the question.
            return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "type": self.type,
            "label": self.label,
            "help_text": self.help_text,
            "options": [{"value": o.value, "label": o.label} for o in self.options],
            "required": self.required,
            "minimum": self.minimum,
            "maximum": self.maximum,
        }


def visible_questions(
    bank: list[Question], answers: dict[str, Any]
) -> list[Question]:
    return [q for q in bank if q.is_visible(answers)]


def validate_answers(
    bank: list[Question], answers: dict[str, Any]
) -> list[str]:
    """Return list of error messages for missing/invalid required answers.

    Empty list = valid.
    """
    errors: list[str] = []
    for q in visible_questions(bank, answers):
        val = answers.get(q.key)
        if q.required and (val is None or val == "" or val == []):
            errors.append(f"{q.label} is required")
            continue
        if val in (None, "", []):
            continue
        if q.type == "number":
            try:
                fval = float(val)
            except (TypeError, ValueError):
                errors.append(f"{q.label}: must be a number")
                continue
            if q.minimum is not None and fval < q.minimum:
                errors.append(f"{q.label}: must be >= {q.minimum}")
            if q.maximum is not None and fval > q.maximum:
                errors.append(f"{q.label}: must be <= {q.maximum}")
        if q.type == "single_select" and q.options:
            allowed = [o.value for o in q.options]
            if val not in allowed:
                errors.append(f"{q.label}: invalid choice")
        if q.type == "multi_select" and q.options:
            allowed = {o.value for o in q.options}
            if not isinstance(val, list) or any(v not in allowed for v in val):
                errors.append(f"{q.label}: invalid choice")
    return errors


def question_banks() -> dict[str, list[Question]]:
    """Lazy registry — imports happen inside to avoid circular deps."""
    from app.masri.compliance.banks import nydfs500, ftc_safeguards

    return {
        "ny_dfs_23nycrr500": nydfs500.QUESTIONS,
        "ftc_safeguards_core": ftc_safeguards.QUESTIONS,
    }


def get_bank(framework_slug: str) -> list[Question]:
    return question_banks().get(framework_slug, [])
