from __future__ import annotations


class TestOutcomeConsistency:
    """Metric B — Test Outcome Consistency.

    Measures whether the agent's patch passes the same test cases across
    transformation variants. Requires test execution (pytest against the
    SWE-bench test suite), which is disabled for the ICSE pilot.
    """

    def compute(self, run_data: list[dict]) -> None:
        # Deferred to TOSEM
        return None
