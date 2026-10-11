"""A reply cut at the token limit is excluded from the outcome metrics, like a timeout.

New runs carry the status "truncated"; runs recorded before it existed (status "no_patch" with
stop_reason "max_tokens") are scored the same way, without rewriting the stored run.
"""
from __future__ import annotations

import json

from stableagent.metrics.outcome import TRUNCATED, scoring_status


def test_a_cut_no_patch_run_is_scored_as_truncated():
    cut = json.dumps({"model": "gpt-4o", "stop_reason": "max_tokens", "patch_source": "tool"})
    assert scoring_status("no_patch", cut) == TRUNCATED == "truncated"
    assert scoring_status("no_patch", {"stop_reason": "max_tokens"}) == "truncated"


def test_other_runs_keep_their_status():
    assert scoring_status("no_patch", json.dumps({"stop_reason": "tool_use"})) == "no_patch"
    assert scoring_status("no_patch", None) == "no_patch"
    assert scoring_status("no_patch", "not json") == "no_patch"
    assert scoring_status("success", json.dumps({"stop_reason": "max_tokens"})) == "success"
    assert scoring_status("truncated", None) == "truncated"


def test_the_engine_excludes_truncated_runs_and_counts_them(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from stableagent.data.models import (
        Base, Experiment, Issue, Metric, Run, TransformedIssue,
    )
    from stableagent.metrics.engine import MetricsEngine

    engine = create_engine(f"sqlite:///{tmp_path / 't.db'}")
    Base.metadata.create_all(engine)
    diff = "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-a\n+b\n"
    with sessionmaker(bind=engine)() as db:
        issue = Issue(external_id="org__x-1", repo_name="org/x", source="manual", issue_text="t")
        exp = Experiment(name="e", config="{}", status="completed")
        db.add_all([issue, exp])
        db.flush()
        rows = {}
        for name in ("original", "paraphrase", "reordering"):
            ti = TransformedIssue(issue_id=issue.id, transformation_name=name,
                                  transformed_text="t", is_original=name == "original")
            db.add(ti)
            db.flush()
            rows[name] = ti
        db.add(Run(experiment_id=exp.id, transformed_issue_id=rows["original"].id,
                   agent_name="a", execution_mode="real", status="success", patch=diff))
        db.add(Run(experiment_id=exp.id, transformed_issue_id=rows["paraphrase"].id,
                   agent_name="a", execution_mode="real", status="no_patch",
                   metadata_=json.dumps({"stop_reason": "max_tokens"})))  # recorded before
        db.add(Run(experiment_id=exp.id, transformed_issue_id=rows["reordering"].id,
                   agent_name="a", execution_mode="real", status="no_patch",
                   metadata_=json.dumps({"stop_reason": "tool_use"})))  # a genuine failure
        db.flush()
        MetricsEngine().compute(exp.id, db)
        metrics = {(m.scope_key, m.metric_name): m for m in db.query(Metric)}

    excluded = metrics[(exp.id, "excluded_runs_status")]
    assert excluded.metric_value == 1
    assert json.loads(excluded.metric_metadata)["by_status"] == {"truncated": 1}
    assert ("a|paraphrase", "transformation_sensitivity") not in metrics  # nothing scored
    assert metrics[("a|reordering", "transformation_sensitivity")].metric_value == 1.0
