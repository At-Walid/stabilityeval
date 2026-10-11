from __future__ import annotations


class AgentRobustnessRanking:
    """Metric H — Agent Robustness Ranking.

    Ranks agents by mean Stability Score (F) across all issues and
    transformations, with optional confidence intervals when runs_per_variant
    > 1.
    """

    def compute(self, run_data: list[dict]) -> None:
        # Deferred to future work
        return None
