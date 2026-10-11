"""SWE-bench Lite loader.

The 300 test issues are bundled in ``data/swebench_lite_issues.json`` (see
scripts/build_swebench_bundle.py), so ``import_bundle`` works offline; ``load_swebench_lite``
can still read the dataset from Hugging Face.

The gold patch (the dataset's ``patch`` field) is kept as HIDDEN ground truth. It is stored in the
issue record's metadata and read only by the metrics engine, to score localization (SPEC section
13). It never reaches an agent: the runner builds AgentInput from the issue text and the repository
name only, so the gold patch cannot appear in a prompt or in an agent's raw logs. It is also left
out of ``repr`` so it cannot leak through logging.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from stableagent.data.models import Issue

DATASET_NAME = "princeton-nlp/SWE-bench_Lite"
GOLD_PATCH_KEY = "gold_patch"
# The 300 test issues bundled with the repository (built by scripts/build_swebench_bundle.py), so
# issues and gold patches can be loaded without any network access.
BUNDLE_PATH = Path(__file__).resolve().parents[3] / "data" / "swebench_lite_issues.json"


@dataclass(frozen=True)
class SWEBenchInstance:
    instance_id: str
    repo: str
    problem_statement: str
    base_commit: str | None = None
    gold_patch: str = field(default="", repr=False)  # hidden ground truth


def instance_from_record(record: dict) -> SWEBenchInstance:
    """One SWE-bench dataset row as an instance (the ``patch`` field becomes the gold patch)."""
    return SWEBenchInstance(
        instance_id=record["instance_id"],
        repo=record["repo"],
        problem_statement=record["problem_statement"],
        base_commit=record.get("base_commit"),
        gold_patch=record.get("patch") or "",
    )


def load_swebench_lite(
    instance_ids: Iterable[str] | None = None,
    *,
    split: str = "test",
    dataset: Iterable[dict] | None = None,
) -> list[SWEBenchInstance]:
    """SWE-bench Lite instances, optionally restricted to ``instance_ids``.

    Downloads the dataset unless ``dataset`` rows are supplied (tests, offline use). Raises
    KeyError if a requested instance id is not in the split.
    """
    if dataset is None:
        from datasets import load_dataset

        dataset = load_dataset(DATASET_NAME, split=split)
    instances = (instance_from_record(record) for record in dataset)
    return _select(instances, instance_ids, f"SWE-bench Lite ({split})")


def load_bundle(
    instance_ids: Iterable[str] | None = None, *, path: Path = BUNDLE_PATH
) -> list[SWEBenchInstance]:
    """The bundled SWE-bench Lite issues, optionally restricted to ``instance_ids``.

    Reads a local JSON file: no network access. Raises KeyError for an unknown instance id.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    instances = (
        SWEBenchInstance(
            instance_id=record["id"],
            repo=record["repo"],
            problem_statement=record["problem_statement"],
            base_commit=record.get("base_commit"),
            gold_patch=record.get("gold_patch") or "",
        )
        for record in data["issues"]
    )
    return _select(instances, instance_ids, "the bundled SWE-bench Lite issues")


def _select(
    instances: Iterable[SWEBenchInstance], instance_ids: Iterable[str] | None, source: str
) -> list[SWEBenchInstance]:
    wanted = set(instance_ids) if instance_ids is not None else None
    selected = [i for i in instances if wanted is None or i.instance_id in wanted]
    if wanted is not None:
        missing = wanted - {instance.instance_id for instance in selected}
        if missing:
            raise KeyError(f"Not in {source}: {sorted(missing)}")
    return selected


@dataclass(frozen=True)
class ImportSummary:
    inserted: int  # issues that were not in the database yet
    updated: int  # issues already present; gold patch attached, text untouched
    kept_text: tuple[str, ...]  # present with a different text (e.g. abridged demo samples)

    @property
    def total(self) -> int:
        return self.inserted + self.updated


def import_bundle(
    db: Session,
    path: Path = BUNDLE_PATH,
    *,
    instance_ids: Iterable[str] | None = None,
) -> ImportSummary:
    """Import the bundled issues (all, or ``instance_ids``) into the issues table, offline.

    Idempotent. Missing issues are inserted with their verbatim text; existing ones keep their
    text and gain the hidden gold patch. Re-importing changes nothing.
    """
    instances = load_bundle(instance_ids, path=path)
    existing = {
        issue.external_id: issue.issue_text
        for issue in db.query(Issue).filter(
            Issue.external_id.in_([instance.instance_id for instance in instances])
        )
    }
    store_instances(db, instances)
    return ImportSummary(
        inserted=sum(1 for i in instances if i.instance_id not in existing),
        updated=sum(1 for i in instances if i.instance_id in existing),
        kept_text=tuple(
            sorted(
                i.instance_id
                for i in instances
                if i.instance_id in existing and existing[i.instance_id] != i.problem_statement
            )
        ),
    )


def store_instances(
    db: Session, instances: Iterable[SWEBenchInstance], *, source: str = "swebench_lite"
) -> dict[str, Issue]:
    """Insert missing issues (with ``source``) and attach each instance's hidden gold patch.

    An issue that already exists keeps its text and source (issue records are immutable); only
    its metadata gains the gold patch and base commit. Returns the issues keyed by instance id.
    """
    issues: dict[str, Issue] = {}
    for instance in instances:
        issue = db.query(Issue).filter(Issue.external_id == instance.instance_id).first()
        if issue is None:
            issue = Issue(
                external_id=instance.instance_id,
                repo_name=instance.repo,
                source=source,
                issue_text=instance.problem_statement,
            )
            db.add(issue)
        metadata = _metadata(issue)
        metadata[GOLD_PATCH_KEY] = instance.gold_patch
        metadata["base_commit"] = instance.base_commit
        serialized = json.dumps(metadata)
        if issue.metadata_ != serialized:  # keep re-imports write-free
            issue.metadata_ = serialized
        issues[instance.instance_id] = issue
    db.flush()
    return issues


def gold_patch_of(issue: Issue) -> str | None:
    """The issue's hidden gold patch, or None (custom issues, demo samples, not loaded yet)."""
    return _metadata(issue).get(GOLD_PATCH_KEY) or None


def _metadata(issue: Issue) -> dict:
    try:
        value = json.loads(issue.metadata_) if issue.metadata_ else {}
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}
