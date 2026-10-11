from __future__ import annotations

from collections import defaultdict
from typing import Optional


class StabilityScore:
    """Metric F — Stability Score (ICSE simplified).

    SS(agent, issue) = w_A × SC + w_C × PatchSim_C1

    ICSE weights:
      No patch similarity  → w_A = 1.0  (SS reduces to SC)
      C1 available         → w_A = 0.7, w_C = 0.3

    Agent-level Stability Score: mean of SS across all issues.
    Range [0, 1]. 1.0 = fully stable; < 0.5 = unstable.
    """

    W_A_NO_PATCH: float = 1.0
    W_A_WITH_PATCH: float = 0.7
    W_C: float = 0.3

    def compute(
        self,
        run_data: list[dict],
        *,
        sc_results: dict[tuple[str, str], float],
        patch_sim_results: Optional[dict[tuple[str, str], float]] = None,
    ) -> dict:
        """Compute SS per (agent, issue) and mean per agent.

        Args:
            run_data:          Raw run data (unused directly; reserved for future use).
            sc_results:        Output of SuccessConsistency.compute().
            patch_sim_results: Optional map (agent, issue_id) → C1 similarity [0,1].
                               When None, w_A=1.0 is used.

        Returns a dict with keys:
            "per_issue": dict[(agent, issue_id) → ss_value]
            "per_agent": dict[agent → mean_ss_across_issues]
        """
        per_issue: dict[tuple[str, str], float] = {}

        for (agent, issue_id), sc in sc_results.items():
            if patch_sim_results and (agent, issue_id) in patch_sim_results:
                c1 = patch_sim_results[(agent, issue_id)]
                ss = self.W_A_WITH_PATCH * sc + self.W_C * c1
            else:
                ss = self.W_A_NO_PATCH * sc
            per_issue[(agent, issue_id)] = ss

        per_agent_vals: dict[str, list[float]] = defaultdict(list)
        for (agent, _), ss in per_issue.items():
            per_agent_vals[agent].append(ss)

        per_agent = {
            agent: sum(vals) / len(vals) for agent, vals in per_agent_vals.items()
        }

        return {"per_issue": per_issue, "per_agent": per_agent}
