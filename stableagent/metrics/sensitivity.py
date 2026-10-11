from __future__ import annotations

from collections import defaultdict

from stableagent.metrics.outcome import outcome_value


class TransformationSensitivity:
    """Metric G — Transformation Sensitivity (ICSE pilot).

    TS(agent, t) = mean_{issues} [ outcome(original) - outcome(t) ]

    where outcome is 1 for success and 0 for failure ("localization success", see
    stableagent.metrics.outcome). Excluded runs (no outcome) contribute no term.

    A positive TS value means transformation t frequently causes the agent to
    fail when it succeeded on the original phrasing. Negative values indicate
    the transformation helped (rare in practice).
    """

    def compute(self, run_data: list[dict]) -> dict[tuple[str, str], float]:
        """Compute TS for every (agent_name, transformation_name) pair.

        run_data items must have keys:
            agent_name, issue_id, is_original (bool),
            transformation_name (str), and outcome (str) or status (str)

        Returns a dict mapping (agent_name, transformation_name) → TS value.
        """
        differences = _outcome_differences(run_data)
        return {key: sum(vals) / len(vals) for key, vals in differences.items()}


class FlipRate:
    """Symmetric flip rate, reported next to TS.

    FR(agent, t) = mean_{issues} | outcome(original) - outcome(t) |

    The fraction of issues whose outcome changes under transformation t, in either direction. TS
    is a drop rate: a success→failure and a failure→success flip cancel out in TS, never here.
    Same exclusions as TS (runs without an outcome contribute no term). Range [0, 1].
    """

    def compute(self, run_data: list[dict]) -> dict[tuple[str, str], float]:
        differences = _outcome_differences(run_data)
        return {key: sum(abs(v) for v in vals) / len(vals) for key, vals in differences.items()}


class ControlFlipRate:
    """Run-to-run noise floor, reported next to the flip rate.

    CFR(agent) = mean_{(issue, control run)} | outcome(original) - outcome(control) |

    A control run re-runs the unchanged original (``control_repeats``), so any flip it shows is
    run-to-run variance, not an effect of phrasing: a transformation's flip rate is a signal only
    where it exceeds this floor. Same exclusions as the flip rate: a control run without an
    outcome contributes no term, and neither does an issue whose original run is excluded.
    """

    def compute(self, run_data: list[dict], control_data: list[dict]) -> dict[str, dict]:
        """agent -> {"value": CFR, "pairs": compared control runs, "flipped": issue ids}.

        ``run_data``: the non-control rows (the originals are read from it); ``control_data``:
        the control runs' rows. Agents without a comparable control run are omitted.
        """
        originals: dict[tuple[str, str], int] = {}
        for row in run_data:
            outcome = outcome_value(row)
            if outcome is not None and row["is_original"]:
                originals[(row["agent_name"], row["issue_id"])] = outcome
        terms: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for row in control_data:
            outcome = outcome_value(row)
            original = originals.get((row["agent_name"], row["issue_id"]))
            if outcome is None or original is None:
                continue
            terms[row["agent_name"]].append((row["issue_id"], abs(original - outcome)))
        return {
            agent: {
                "value": sum(flip for _, flip in pairs) / len(pairs),
                "pairs": len(pairs),
                "flipped": sorted({issue_id for issue_id, flip in pairs if flip}),
            }
            for agent, pairs in terms.items()
        }


def _outcome_differences(run_data: list[dict]) -> dict[tuple[str, str], list[int]]:
    """(agent, transformation) -> outcome(original) - outcome(t), one entry per issue."""
    # Collect outcomes per (agent, issue): {"original" or transform_name → 0|1}
    outcomes: dict[tuple[str, str], dict[str, int]] = defaultdict(dict)

    for row in run_data:
        outcome = outcome_value(row)
        if outcome is None:
            continue
        key = (row["agent_name"], row["issue_id"])
        # Use a fixed "original" key for the original run so that the
        # actual transformation_name of the original TI is irrelevant.
        transform_key = "original" if row["is_original"] else row["transformation_name"]
        outcomes[key][transform_key] = outcome

    # Accumulate per-issue differences for each (agent, transform)
    differences: dict[tuple[str, str], list[int]] = defaultdict(list)

    for (agent, _issue_id), issue_outcomes in outcomes.items():
        if "original" not in issue_outcomes:
            continue
        orig = issue_outcomes["original"]
        for transform_name, t_outcome in issue_outcomes.items():
            if transform_name == "original":
                continue
            differences[(agent, transform_name)].append(orig - t_outcome)
    return differences
