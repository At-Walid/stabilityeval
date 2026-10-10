"""Transformation cache: one stored variant per (issue, transformation, params, version, generator).

Every stored variant records its provenance (SPEC section 11.6): ``generator`` (the model id of an
LLM-backed transformation, "deterministic", or "placeholder"), ``transform_version`` and the
execution mode it was produced in, plus ``noop`` (identical to the original after whitespace
normalization; excluded from SC/TS).

Placeholders exist only in the modes that make no API calls (mock, dry-run). In real mode an
LLM-backed variant is generated or the run fails with a TransformationError: never a placeholder.

An LLM-backed variant is generated with its code masked (SPEC section 11.7): the placeholders are
checked, the code restored, and only then is the quality check run. At most two attempts: a failed
first attempt is retried once with feedback naming what went wrong; a variant still failing is
stored and excluded ("placeholder_lost" when its code could not be restored). A transformation's
``reuses_passed_versions`` keeps the variants of those older versions that passed the quality
check: they are served from the cache instead of being regenerated.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import replace
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from stability_eval.config.settings import redact_api_key
from stability_eval.data.models import TransformedIssue as TransformedIssueModel
from stability_eval.transformations.base import (
    PLACEHOLDER,
    AbstractTransformation,
    IssueRecord,
    TransformedIssue,
    check_identifier_retention,
    is_noop,
)

log = logging.getLogger(__name__)

# An LLM-backed output that fails the placeholder or quality check (identifier retention, plus any
# invented details the transformation checks) is regenerated this many times, with feedback; if
# every attempt fails, the variant is stored with quality_warning=True and the metrics engine
# excludes it (SPEC sections 11.5, 11.7 and 13). Two attempts in total.
MAX_QUALITY_RETRIES = 1
# Execution modes that make no API calls: LLM-backed variants are never generated in them.
OFFLINE_MODES = frozenset({"mock", "dry_run"})
# Kept in the params of placeholders stored before provenance existed (see data/migrations.py).
OFFLINE_PLACEHOLDER_KEY = "offline_placeholder"
# The exclusion_reason of a no-op variant (data/migrations.py writes the same text).
NOOP_REASON = "no-op: identical to the original after whitespace normalization"
# The exclusion_reason prefix of a variant whose code placeholders did not all come back exactly
# once, so its code could not be restored (SPEC section 11.7).
PLACEHOLDER_LOST = "placeholder_lost"


class TransformationError(RuntimeError):
    """A variant could not be generated. Real mode never substitutes a placeholder for it."""


def cache_key(
    transformation: AbstractTransformation,
    params: dict,
    generator: str | None = None,
    version: str | None = None,
) -> str:
    """sha256 over the params, the ``transform_version`` (or ``version``) and the generator.

    Bumping the version, or changing the model behind an LLM-backed transformation, changes the
    key, so variants produced by an older prompt, algorithm or model are never reused; they stay in
    the database for the experiments that already ran on them. A placeholder is keyed with the
    generator "placeholder", so a real-mode lookup can never return one.
    """
    payload = {
        "params": params,
        "transform_version": version or transformation.transform_version,
        "generator": generator or transformation.generator,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def find_cached_variant(
    session: Session,
    issue_db_id: str,
    transformation: AbstractTransformation,
    params: dict,
    generator: str | None = None,
) -> TransformedIssueModel | None:
    """The stored variant of an issue for this transformation, params, version and generator.

    ``generator`` defaults to the transformation's own (its model, or "deterministic"). Without
    one for the current version, a variant of a version in ``reuses_passed_versions`` that passed
    the quality check (a no-op included) is returned.
    """
    rows = [
        (_stored_params(row).get("_cache_key"), row)
        for row in session.query(TransformedIssueModel)
        .filter_by(issue_id=issue_db_id, transformation_name=transformation.name)
        .order_by(TransformedIssueModel.created_at)
    ]
    key = cache_key(transformation, params, generator)
    for stored_key, row in rows:
        if stored_key == key:
            return row
    for version in sorted(transformation.reuses_passed_versions, reverse=True):
        key = cache_key(transformation, params, generator, version)
        for stored_key, row in rows:
            if stored_key == key and not row.quality_warning:
                return row
    return None


def is_cached(row: TransformedIssueModel) -> bool:
    """Whether a stored variant still has its cache key (a lookup can return it)."""
    return "_cache_key" in _stored_params(row)


def uncache(row: TransformedIssueModel, reason: str) -> bool:
    """Remove a stored variant's cache key, so no lookup returns it and the next run regenerates
    it. The row stays (with ``reason`` and a timestamp) for the runs that used it. Returns False
    when it was not cached."""
    stored = _stored_params(row)
    if stored.pop("_cache_key", None) is None:
        return False
    stored["invalidated"] = f"{reason} at {datetime.now(timezone.utc).isoformat()}"
    row.transformation_params = json.dumps(stored)
    return True


class TransformationCache:
    """Cache transformation results in the database (see the module docstring).

    On a cache hit: return the stored variant with zero API cost. On a miss: generate it
    (LLM-backed outputs must pass the quality check, with retries) and store it with its
    provenance, or, in an offline mode, store a placeholder for an LLM-backed transformation.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def variant(
        self,
        transformation: AbstractTransformation,
        issue: IssueRecord,
        params: dict,
        *,
        mode: str = "real",
        recorded: dict | None = None,
    ) -> TransformedIssueModel:
        """The stored variant to run on in ``mode`` ("real", "mock" or "dry_run").

        - Deterministic transformations: cached, else computed (in any mode).
        - LLM-backed, real mode: cached, else generated. A generation failure (no API key, API
          error) raises TransformationError; there is no fallback.
        - LLM-backed, mock / dry-run: the generated variant if one is cached, else a placeholder
          (stored under its own key, reused by later offline runs, never served in real mode).
        - Mock / dry-run, on a cache miss, first: the variant a MockReplay fixture recorded
          (``recorded``, see ``restore_recorded``) when it is one the cache would serve. A replay
          then runs on the very variant the recorded experiment ran on, deterministic ones
          included (typo injection without a seed differs from one computation to the next).
        """
        row = find_cached_variant(self._session, issue.issue_id, transformation, params)
        if row is not None:
            log.debug("Cache hit: issue=%s transformation=%s", issue.issue_id, transformation.name)
            return row
        if recorded and mode in OFFLINE_MODES:
            restored = self.restore_recorded(transformation, issue, params, recorded)
            if restored is not None:
                return restored
        if transformation.category == "llm_backed" and mode in OFFLINE_MODES:
            return self._placeholder(transformation, issue, params, mode)

        result, problems, cost = self._generate(transformation, issue, params)
        row = self._store(
            transformation, issue, params,
            text=result.transformed_text,
            notes=result.transformation_notes,
            generator=transformation.generator,
            mode=mode,
            quality_warning=problems is not None,
            exclusion_reason=_describe(problems, limit=50) if problems else None,
            generation_cost_usd=cost,
        )
        if transformation.category == "llm_backed":
            self._invalidate_placeholders(transformation, issue)
        return row

    def get_or_transform(
        self,
        transformation: AbstractTransformation,
        issue: IssueRecord,
        params: dict,
        *,
        mode: str = "real",
    ) -> TransformedIssue:
        """``variant`` as a TransformedIssue dataclass (scripts and the CLI preview use this)."""
        row = self.variant(transformation, issue, params, mode=mode)
        return TransformedIssue(
            original_issue_id=row.issue_id,
            transformation_name=row.transformation_name,
            transformation_params=_stored_params(row).get("params", params),
            transformed_text=row.transformed_text,
            transformation_notes=row.transformation_notes or "",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _store(
        self,
        transformation: AbstractTransformation,
        issue: IssueRecord,
        params: dict,
        *,
        text: str,
        notes: str,
        generator: str,
        mode: str,
        quality_warning: bool = False,
        noop: bool | None = None,
        exclusion_reason: str | None = None,
        generation_cost_usd: float | None = 0.0,
        version: str | None = None,
        extra_params: dict | None = None,
    ) -> TransformedIssueModel:
        noop = is_noop(issue.text, text) if noop is None else noop
        if noop and exclusion_reason is None:
            exclusion_reason = NOOP_REASON
        version = version or transformation.transform_version
        row = TransformedIssueModel(
            issue_id=issue.issue_id,
            transformation_name=transformation.name,
            transformation_params=json.dumps({
                "params": params,
                "transform_version": version,
                "generator": generator,
                **(extra_params or {}),
                "_cache_key": cache_key(transformation, params, generator, version),
            }),
            transformed_text=text,
            transformation_notes=notes,
            quality_warning=quality_warning,
            is_original=False,
            generator=generator,
            transform_version=version,
            generation_mode=mode,
            noop=noop,
            exclusion_reason=exclusion_reason,
            generation_cost_usd=generation_cost_usd,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def restore_recorded(
        self,
        transformation: AbstractTransformation,
        issue: IssueRecord,
        params: dict,
        recorded: dict,
    ) -> TransformedIssueModel | None:
        """Store the variant a MockReplay fixture recorded (``recorded_variant``) as the cached
        variant, provenance and flags included, so an offline replay runs on the very variant the
        recorded experiment ran on. None, and nothing stored, unless the cache itself would serve
        it: same original text, params and generator, and the current version or a passed variant
        of a version in ``reuses_passed_versions``. Never generates anything."""
        version = str(recorded.get("transform_version") or "")
        acceptable_version = version == transformation.transform_version or (
            version in transformation.reuses_passed_versions
            and not recorded.get("quality_warning")
        )
        if not (
            acceptable_version
            and recorded.get("generator") == transformation.generator
            and recorded.get("params", {}) == params
            and recorded.get("original_sha256") == _sha256(issue.text)
            and isinstance(recorded.get("transformed_text"), str)
        ):
            return None
        row = self._store(
            transformation, issue, params,
            text=recorded["transformed_text"],
            notes=recorded.get("transformation_notes") or "",
            generator=transformation.generator,
            mode=recorded.get("generation_mode") or "unknown",
            quality_warning=bool(recorded.get("quality_warning")),
            noop=bool(recorded.get("noop")),
            exclusion_reason=recorded.get("exclusion_reason"),
            generation_cost_usd=recorded.get("generation_cost_usd"),
            version=version,
            extra_params={"restored_from": "mock_replay fixture"},
        )
        if transformation.category == "llm_backed":
            self._invalidate_placeholders(transformation, issue)
        log.info(
            "Restored the recorded %s variant of %s from its MockReplay fixture",
            transformation.name, issue.issue_id,
        )
        return row

    def _placeholder(
        self, transformation: AbstractTransformation, issue: IssueRecord, params: dict, mode: str
    ) -> TransformedIssueModel:
        row = find_cached_variant(
            self._session, issue.issue_id, transformation, params, PLACEHOLDER
        )
        if row is not None:
            return row
        note = (
            f"[Offline placeholder: the {transformation.name} variant was not generated because "
            f"{mode} mode makes no API calls. Run in real mode to generate it. The original text "
            "follows.]"
        )
        # Never a no-op: it is not a transformation at all, and its generator says so.
        return self._store(
            transformation, issue, params,
            text=f"{note}\n\n{issue.text}", notes=note, generator=PLACEHOLDER, mode=mode,
            noop=False,
        )

    def _invalidate_placeholders(
        self, transformation: AbstractTransformation, issue: IssueRecord
    ) -> None:
        """A generated variant now exists: no placeholder of this issue/transformation is reused."""
        rows = (
            self._session.query(TransformedIssueModel)
            .filter_by(issue_id=issue.issue_id, transformation_name=transformation.name,
                       generator=PLACEHOLDER)
            .all()
        )
        for row in rows:
            uncache(row, "superseded by a generated variant")
        self._session.flush()

    @staticmethod
    def _generate(
        transformation: AbstractTransformation, issue: IssueRecord, params: dict
    ) -> tuple[TransformedIssue, dict[str, list[str]] | None, float]:
        """Run the transformation; returns (result, problems, API cost of all attempts), problems
        None when it passed.

        An LLM-backed attempt must keep every code placeholder exactly once (its code is then
        restored byte for byte); only then is the quality check run: the original's code verbatim
        and its technical tokens (identifier-retention check), and no detail the transformation
        checks for (``invented_details``). A failing attempt is retried MAX_QUALITY_RETRIES times
        with feedback naming the problems; if every attempt fails, the best one (restorable
        first, then fewest problems) is returned with its problems (the variant gets
        quality_warning=True). Any error raised by the transformation (no API key, API failure)
        becomes a TransformationError.
        """
        if transformation.category != "llm_backed":
            return _transform(transformation, issue, params), None, 0.0

        attempts = 1 + MAX_QUALITY_RETRIES
        label = issue.metadata.get("external_id") or issue.issue_id
        cost = 0.0
        best: TransformedIssue | None = None
        best_problems: dict[str, list[str]] = {}
        result: TransformedIssue | None = None
        problems: dict[str, list[str]] = {}
        for attempt in range(1, attempts + 1):
            retry = None if result is None else (result, problems)
            result = _transform(transformation, issue, params, retry=retry)
            cost += result.generation_cost_usd
            problems = _quality_problems(transformation, issue.text, result)
            if not problems:
                note = f"quality check passed on attempt {attempt}/{attempts}"
                return _with_note(result, note), None, cost
            log.warning(
                "Quality check FAILED for %s/%s (attempt %d/%d): %s",
                label, transformation.name, attempt, attempts, _describe(problems),
            )
            if best is None or _rank(problems) < _rank(best_problems):
                best, best_problems = result, problems

        log.warning(
            "Quality warning: %s/%s failed the quality check after %d attempts; the variant "
            "is excluded from metrics",
            label, transformation.name, attempts,
        )
        note = (
            f"QUALITY WARNING: {_describe(best_problems)} after {attempts} attempts; "
            "excluded from metrics"
        )
        return _with_note(best, note), best_problems, cost


def _transform(
    transformation: AbstractTransformation,
    issue: IssueRecord,
    params: dict,
    *,
    retry: tuple[TransformedIssue, dict[str, list[str]]] | None = None,
) -> TransformedIssue:
    """One attempt; ``retry`` is (the previous attempt, its problems) for a retry with feedback."""
    try:
        if retry is None:
            return transformation.transform(issue, params)
        previous, problems = retry
        return transformation.retry(issue, params, previous, _feedback(problems))
    except Exception as exc:
        label = issue.metadata.get("external_id") or issue.issue_id
        message = (
            f"Could not generate the {transformation.name} variant of issue {label} with "
            f"{transformation.generator}: {redact_api_key(f'{type(exc).__name__}: {exc}')}."
        )
        if transformation.category == "llm_backed":
            message += (
                " Real mode never substitutes a placeholder: check the API key and network "
                "access, then run again (variants already generated are cached)."
            )
        raise TransformationError(message) from exc


def _quality_problems(
    transformation: AbstractTransformation, original: str, result: TransformedIssue
) -> dict[str, list[str]]:
    """The attempt's problems: its placeholder problems if its code could not be restored, else
    the quality check's (missing technical content, invented details)."""
    if result.placeholder_problems:
        return {"placeholders": list(result.placeholder_problems)}
    _passed, missing = check_identifier_retention(original, result.transformed_text)
    problems = {
        "missing": sorted(missing),
        "invented": transformation.invented_details(original, result.transformed_text),
    }
    return {kind: items for kind, items in problems.items() if items}


def _rank(problems: dict[str, list[str]]) -> tuple[bool, int]:
    """Lower is better: a restorable attempt first, then the fewest problems."""
    return "placeholders" in problems, sum(len(items) for items in problems.values())


def _feedback(problems: dict[str, list[str]]) -> str:
    """What the model is told before its second attempt."""
    if "placeholders" in problems:
        return (
            "Your answer did not keep every code placeholder exactly once: "
            f"{'; '.join(problems['placeholders'])}. Answer again in the same format: every "
            "placeholder of the input must appear exactly once, written exactly as given; you "
            "may move a placeholder but never edit or drop it."
        )
    parts = []
    if "missing" in problems:
        parts.append(
            "it dropped technical content that must appear verbatim: "
            + ", ".join(problems["missing"])
        )
    if "invented" in problems:
        parts.append(
            "it mentions details the original does not contain: "
            + ", ".join(problems["invented"])
        )
    return (
        f"Your answer failed the quality check: {'; '.join(parts)}. Answer again in the same "
        "format, fixing this; every placeholder must still appear exactly once."
    )


def _describe(problems: dict[str, list[str]], limit: int = 10) -> str:
    parts = []
    if "placeholders" in problems:
        lost = problems["placeholders"]
        shown = ", ".join(lost[:limit]) + (" ..." if len(lost) > limit else "")
        parts.append(f"{PLACEHOLDER_LOST}: {shown}")
    if "missing" in problems:
        missing = problems["missing"]
        shown = ", ".join(missing[:limit]) + (" ..." if len(missing) > limit else "")
        parts.append(f"identifier retention failed (missing {len(missing)}: {shown})")
    if "invented" in problems:
        parts.append(f"invented details ({', '.join(problems['invented'])})")
    return "; ".join(parts)


def _with_note(result: TransformedIssue, note: str) -> TransformedIssue:
    notes = f"{result.transformation_notes} [{note}]" if result.transformation_notes else f"[{note}]"
    return replace(result, transformation_notes=notes)


def recorded_variant(row: TransformedIssueModel, original_text: str) -> dict:
    """The variant a run used, as a MockReplay fixture records it (``restore_recorded`` reads it):
    text, params and provenance, plus a hash of the original text it was produced from."""
    return {
        "transformed_text": row.transformed_text,
        "transformation_notes": row.transformation_notes,
        "params": _stored_params(row).get("params", {}),
        "generator": row.generator,
        "transform_version": row.transform_version,
        "generation_mode": row.generation_mode,
        "quality_warning": bool(row.quality_warning),
        "noop": bool(row.noop),
        "exclusion_reason": row.exclusion_reason,
        "generation_cost_usd": row.generation_cost_usd,
        "original_sha256": _sha256(original_text),
    }


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stored_params(row: TransformedIssueModel) -> dict:
    try:
        value = json.loads(row.transformation_params or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
