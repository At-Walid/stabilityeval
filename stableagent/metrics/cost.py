from __future__ import annotations


class CostMetrics:
    """Metrics I4–I5 — Cost and Runtime (optional in the ICSE pilot).

    I4: Mean cost per successful repair (USD).
    I5: Timeout rate — fraction of runs that exceeded the per-run time limit.
    """

    def compute(self, run_data: list[dict]) -> None:
        # Deferred to future work
        return None
