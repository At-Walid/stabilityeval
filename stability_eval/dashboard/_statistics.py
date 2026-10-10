from __future__ import annotations

from collections.abc import Iterable
from math import comb

import pandas as pd


def _holm_adjust(p_values: list[float]) -> list[float]:
    """Return Holm-adjusted p-values in their original order."""
    order = sorted(range(len(p_values)), key=p_values.__getitem__)
    adjusted = [0.0] * len(p_values)
    running_max = 0.0
    count = len(p_values)
    for rank, index in enumerate(order):
        running_max = max(running_max, (count - rank) * p_values[index])
        adjusted[index] = min(1.0, running_max)
    return adjusted


def _exact_mcnemar_p(regressions: int, improvements: int) -> float:
    """Two-sided exact McNemar p-value from the discordant paired outcomes."""
    discordant = regressions + improvements
    if discordant == 0:
        return 1.0
    tail = sum(comb(discordant, k) for k in range(min(regressions, improvements) + 1))
    return min(1.0, 2.0 * tail / (2 ** discordant))


def paired_transformation_tests(rows: Iterable[dict]) -> tuple[list[dict], int]:
    """Exact paired tests of each transformed outcome against its original.

    The independent unit is an issue. Rows carrying an "outcome" (the metrics engine's
    localization-success outcome, as the dashboard attaches it) are tested on that outcome;
    rows with only a "status" fall back to it. Rows without a binary outcome (excluded runs),
    missing counterparts, or duplicate issue/variant outcomes are excluded.
    """
    frame = pd.DataFrame(rows)
    label = "outcome" if "outcome" in frame.columns else "status"
    if frame.empty or not {"issue_id", "transformation_name", label}.issubset(frame.columns):
        return [], 0

    eligible = frame[frame[label].isin(["success", "failure"])].copy()
    eligible["success"] = eligible[label].eq("success")
    duplicate_mask = eligible.duplicated(
        ["issue_id", "transformation_name"], keep=False
    )
    duplicate_pairs = eligible.loc[
        duplicate_mask, ["issue_id", "transformation_name"]
    ].drop_duplicates()
    eligible = eligible.loc[~duplicate_mask]

    outcomes = eligible.pivot(
        index="issue_id", columns="transformation_name", values="success"
    )
    if "original" not in outcomes.columns:
        return [], len(duplicate_pairs)

    tests: list[dict] = []
    for transformation in outcomes.columns:
        if transformation == "original":
            continue
        paired = outcomes[["original", transformation]].dropna()
        if paired.empty:
            continue

        original = paired["original"].astype(bool)
        transformed = paired[transformation].astype(bool)
        regressions = int((original & ~transformed).sum())
        improvements = int((~original & transformed).sum())
        p_value = _exact_mcnemar_p(regressions, improvements)
        tests.append({
            "transformation": transformation,
            "n_pairs": int(len(paired)),
            "original_successes": int(original.sum()),
            "transformed_successes": int(transformed.sum()),
            "regressions": regressions,
            "improvements": improvements,
            "success_rate_delta": float(transformed.mean() - original.mean()),
            "p_value": p_value,
        })

    adjusted = _holm_adjust([row["p_value"] for row in tests])
    for row, p_adjusted in zip(tests, adjusted):
        row["p_holm"] = p_adjusted
    return tests, len(duplicate_pairs)
