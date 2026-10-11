from __future__ import annotations

from collections import defaultdict

from stableagent.metrics.outcome import outcome_value


class SuccessConsistency:
    """Metric A — Success Consistency (ICSE pilot).

    SC(agent, issue) = |{v : outcome(v) = outcome(original)}| / |variants|

    Compares each transformation variant's success/failure outcome ("localization success",
    see stableagent.metrics.outcome) against the original. Range [0, 1]. A score of 1 means
    the agent produces the same outcome regardless of how the issue is phrased. Excluded runs
    (no outcome) are ignored.
    """

    def compute(self, run_data: list[dict]) -> dict[tuple[str, str], float]:
        """Compute SC for every (agent_name, issue_id) pair found in run_data.

        run_data items must have keys:
            agent_name, issue_id, is_original (bool), and outcome (str) or status (str)

        Returns a dict mapping (agent_name, issue_id) → SC value.
        Pairs that have no original run or no variant runs are omitted.
        """
        groups: dict[tuple[str, str], dict] = defaultdict(
            lambda: {"original": None, "variants": []}
        )

        for row in run_data:
            outcome = outcome_value(row)
            if outcome is None:
                continue
            key = (row["agent_name"], row["issue_id"])
            if row["is_original"]:
                groups[key]["original"] = outcome
            else:
                groups[key]["variants"].append(outcome)

        results: dict[tuple[str, str], float] = {}
        for (agent, issue_id), data in groups.items():
            original = data["original"]
            variants = data["variants"]
            if original is None or not variants:
                continue
            matching = sum(1 for outcome in variants if outcome == original)
            results[(agent, issue_id)] = matching / len(variants)

        return results
