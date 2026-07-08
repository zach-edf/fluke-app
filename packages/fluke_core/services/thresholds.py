"""Pass/fail evaluation for workflow capture steps.

This module is intentionally pure (no BLE, Qt, or SQLite) so it can be unit
tested in isolation and reused by the workflow runner, CLI, and desktop UI.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from fluke_core.enums import WorkflowVerdict
from fluke_core.models.workflow import (
    AcceptanceCriteria,
    RELATIVE_MODE_MAX_UNBALANCE,
    RELATIVE_MODE_PERCENT_DROP,
    RELATIVE_MODE_PERCENT_OF_REFERENCE,
    RELATIVE_MODE_PERCENT_WITHIN,
    WorkflowStep,
)


@dataclass(frozen=True, slots=True)
class ThresholdEvaluation:
    """Result of evaluating a capture value against acceptance criteria."""

    verdict: WorkflowVerdict
    detail: str
    failed_limit: str | None = None

    @property
    def passed(self) -> bool:
        return self.verdict == WorkflowVerdict.PASS

    @property
    def failed(self) -> bool:
        return self.verdict == WorkflowVerdict.FAIL


def _fmt(value: float) -> str:
    text = f"{value:.6g}"
    return text


def evaluate_step(
    step: WorkflowStep,
    value: float | None,
    reference_values: Mapping[str, float | None] | None = None,
) -> ThresholdEvaluation:
    """Evaluate a captured ``value`` against a step's acceptance criteria.

    ``reference_values`` maps prior ``step_id`` values captured earlier in the
    same run and is only consulted for relative criteria.
    """

    criteria = step.acceptance
    if criteria is None or criteria.is_empty:
        return ThresholdEvaluation(WorkflowVerdict.NOT_EVALUATED, "No acceptance criteria.")
    return evaluate_criteria(criteria, value, reference_values, unit=step.expected_unit)


def evaluate_criteria(
    criteria: AcceptanceCriteria,
    value: float | None,
    reference_values: Mapping[str, float | None] | None = None,
    *,
    unit: str | None = None,
) -> ThresholdEvaluation:
    references = dict(reference_values or {})
    unit_text = f" {criteria.unit or unit}" if (criteria.unit or unit) else ""

    if criteria.is_empty:
        return ThresholdEvaluation(WorkflowVerdict.NOT_EVALUATED, "No acceptance criteria.")

    if value is None:
        return ThresholdEvaluation(
            WorkflowVerdict.NOT_EVALUATED,
            "No numeric reading captured; acceptance criteria not evaluated.",
        )

    failures: list[str] = []
    passes: list[str] = []

    # Absolute limits.
    if criteria.min_value is not None:
        if value < criteria.min_value:
            failures.append(f"below min {_fmt(criteria.min_value)}{unit_text}")
        else:
            passes.append(f">= min {_fmt(criteria.min_value)}{unit_text}")
    if criteria.max_value is not None:
        if value > criteria.max_value:
            failures.append(f"above max {_fmt(criteria.max_value)}{unit_text}")
        else:
            passes.append(f"<= max {_fmt(criteria.max_value)}{unit_text}")

    # Relative limits.
    if criteria.has_relative:
        relative = _evaluate_relative(criteria, value, references, unit_text)
        if relative.verdict == WorkflowVerdict.NOT_EVALUATED:
            # Missing reference: if nothing else was evaluated, report not-evaluated.
            if not failures and not passes:
                return relative
        elif relative.verdict == WorkflowVerdict.FAIL:
            failures.append(relative.detail)
        else:
            passes.append(relative.detail)

    if failures:
        detail = f"FAIL: measured {_fmt(value)}{unit_text} " + "; ".join(failures)
        return ThresholdEvaluation(WorkflowVerdict.FAIL, detail, failed_limit="; ".join(failures))
    detail = f"PASS: measured {_fmt(value)}{unit_text} within " + ("; ".join(passes) if passes else "limits")
    return ThresholdEvaluation(WorkflowVerdict.PASS, detail)


def _evaluate_relative(
    criteria: AcceptanceCriteria,
    value: float,
    references: dict[str, float | None],
    unit_text: str,
) -> ThresholdEvaluation:
    mode = criteria.relative_mode
    percent = criteria.percent
    if percent is None:
        return ThresholdEvaluation(
            WorkflowVerdict.NOT_EVALUATED,
            f"Relative criterion {mode!r} is missing a percent tolerance.",
        )

    if mode == RELATIVE_MODE_MAX_UNBALANCE:
        return _evaluate_unbalance(criteria, value, references, percent, unit_text)

    ref_id = criteria.reference_step_id
    if not ref_id:
        return ThresholdEvaluation(
            WorkflowVerdict.NOT_EVALUATED,
            f"Relative criterion {mode!r} is missing a reference step id.",
        )
    if ref_id not in references or references.get(ref_id) is None:
        return ThresholdEvaluation(
            WorkflowVerdict.NOT_EVALUATED,
            f"Reference step {ref_id!r} has no captured value; relative criterion not evaluated.",
        )
    reference = float(references[ref_id])
    if reference == 0:
        return ThresholdEvaluation(
            WorkflowVerdict.NOT_EVALUATED,
            f"Reference step {ref_id!r} captured zero; relative criterion not evaluated.",
        )

    if mode in (RELATIVE_MODE_PERCENT_WITHIN, RELATIVE_MODE_PERCENT_OF_REFERENCE):
        deviation = abs(value - reference) / abs(reference) * 100.0
        band = f"within {_fmt(percent)}% of {_fmt(reference)}{unit_text} (step {ref_id})"
        if deviation > percent:
            return ThresholdEvaluation(
                WorkflowVerdict.FAIL,
                f"deviates {_fmt(deviation)}% from reference (limit {_fmt(percent)}%, step {ref_id})",
            )
        return ThresholdEvaluation(WorkflowVerdict.PASS, band)

    if mode == RELATIVE_MODE_PERCENT_DROP:
        drop = (reference - value) / abs(reference) * 100.0
        floor = reference * (1.0 - percent / 100.0)
        if drop > percent:
            return ThresholdEvaluation(
                WorkflowVerdict.FAIL,
                f"dropped {_fmt(drop)}% below reference {_fmt(reference)}{unit_text} "
                f"(limit {_fmt(percent)}%, floor {_fmt(floor)}{unit_text}, step {ref_id})",
            )
        return ThresholdEvaluation(
            WorkflowVerdict.PASS,
            f"drop {_fmt(max(drop, 0.0))}% within {_fmt(percent)}% of {_fmt(reference)}{unit_text} (step {ref_id})",
        )

    return ThresholdEvaluation(
        WorkflowVerdict.NOT_EVALUATED,
        f"Unsupported relative mode {mode!r}.",
    )


def _evaluate_unbalance(
    criteria: AcceptanceCriteria,
    value: float,
    references: dict[str, float | None],
    percent: float,
    unit_text: str,
) -> ThresholdEvaluation:
    ref_ids = list(criteria.reference_step_ids)
    values = [value]
    missing: list[str] = []
    for ref_id in ref_ids:
        ref_value = references.get(ref_id)
        if ref_value is None:
            missing.append(ref_id)
        else:
            values.append(float(ref_value))
    if missing:
        return ThresholdEvaluation(
            WorkflowVerdict.NOT_EVALUATED,
            f"Unbalance reference step(s) {', '.join(missing)} have no captured value; not evaluated.",
        )
    if len(values) < 2:
        return ThresholdEvaluation(
            WorkflowVerdict.NOT_EVALUATED,
            "Unbalance criterion needs at least two captured phases; not evaluated.",
        )
    average = sum(values) / len(values)
    if average == 0:
        return ThresholdEvaluation(
            WorkflowVerdict.NOT_EVALUATED,
            "Phase average is zero; unbalance not evaluated.",
        )
    max_deviation = max(abs(v - average) for v in values)
    unbalance = max_deviation / abs(average) * 100.0
    if unbalance > percent:
        return ThresholdEvaluation(
            WorkflowVerdict.FAIL,
            f"phase unbalance {_fmt(unbalance)}% exceeds limit {_fmt(percent)}% "
            f"(avg {_fmt(average)}{unit_text})",
            failed_limit=f"unbalance limit {_fmt(percent)}%",
        )
    return ThresholdEvaluation(
        WorkflowVerdict.PASS,
        f"phase unbalance {_fmt(unbalance)}% within {_fmt(percent)}% (avg {_fmt(average)}{unit_text})",
    )


def combine_run_verdict(step_verdicts: list[WorkflowVerdict]) -> WorkflowVerdict:
    """Roll individual step verdicts up to an overall run verdict."""

    if any(v == WorkflowVerdict.FAIL for v in step_verdicts):
        return WorkflowVerdict.FAIL
    if any(v == WorkflowVerdict.PASS for v in step_verdicts):
        return WorkflowVerdict.PASS
    return WorkflowVerdict.NOT_EVALUATED
