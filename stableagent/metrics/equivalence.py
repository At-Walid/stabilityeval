from __future__ import annotations


class BehavioralEquivalenceRate:
    """Metric E — Behavioral Equivalence Rate.

    Fraction of (original, variant) pairs where the agent's behavior is
    judged fully equivalent, combining test outcome, patch similarity, and
    output similarity into a single binary equivalence judgment.
    """

    def compute(self, run_data: list[dict]) -> None:
        # Deferred to future work
        return None
