from __future__ import annotations


class CostLimitExceeded(Exception):
    """Raised by CostGuard.record_run when the total experiment cost limit is reached."""


class CostGuard:
    """Tracks cumulative experiment cost and enforces per-run and total limits.

    Usage:
        guard = CostGuard(per_run_cap=0.50, total_limit=20.0)
        if guard.check_run(guard.running_total, guard.per_run_cap, guard.total_limit):
            output = adapter.run(...)
            guard.record_run(output.cost_usd)   # raises CostLimitExceeded if over budget
    """

    def __init__(self, per_run_cap: float, total_limit: float) -> None:
        self._per_run_cap = per_run_cap
        self._total_limit = total_limit
        self._running_total: float = 0.0

    @property
    def running_total(self) -> float:
        return self._running_total

    @property
    def per_run_cap(self) -> float:
        return self._per_run_cap

    @property
    def total_limit(self) -> float:
        return self._total_limit

    def check_run(self, current_total: float, per_run_cap: float, total_limit: float) -> bool:
        """Return True if a new run may proceed given the budget state.

        A run is allowed when current_total is still strictly below total_limit
        (another run could contribute up to per_run_cap, but we do not pre-charge it
        because mock/dry-run costs are zero and real costs are only known after the run).
        """
        return current_total < total_limit

    def record_run(self, cost_usd: float) -> None:
        """Add *cost_usd* to the running total; raise CostLimitExceeded if the total limit is hit."""
        self._running_total += cost_usd
        if self._running_total >= self._total_limit:
            raise CostLimitExceeded(
                f"Total experiment cost ${self._running_total:.4f} reached "
                f"the configured limit of ${self._total_limit:.2f}"
            )
