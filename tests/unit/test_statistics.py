"""The bootstrap CI and the Wilcoxon signed-rank test behind the changed-line similarity
(stability_eval.metrics.statistics), checked against SciPy's documented results."""
from __future__ import annotations

import math

import numpy as np
import pytest

from stability_eval.metrics.statistics import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    EXACT,
    NORMAL,
    UNDEFINED,
    bootstrap_mean_ci,
    wilcoxon_signed_rank,
)

# The example of the scipy.stats.wilcoxon documentation (differences in height of paired plants).
SCIPY_EXAMPLE = [6, 8, 14, 16, 23, 24, 28, 29, 41, -48, 49, 56, 60, -67, 75]


def test_wilcoxon_exact_matches_scipy_documentation():
    result = wilcoxon_signed_rank(SCIPY_EXAMPLE)
    assert result.method == EXACT
    assert result.statistic == 24.0
    assert result.p_value == pytest.approx(0.041259765625, abs=1e-15)
    assert result.n == 15


def test_wilcoxon_normal_approximation_matches_scipy_documentation():
    result = wilcoxon_signed_rank(SCIPY_EXAMPLE, method=NORMAL)
    assert result.method == NORMAL
    assert result.p_value == pytest.approx(0.04088813291185591, rel=1e-9)


def test_wilcoxon_is_symmetric_in_the_sign_of_the_differences():
    flipped = wilcoxon_signed_rank([-d for d in SCIPY_EXAMPLE])
    assert flipped.p_value == wilcoxon_signed_rank(SCIPY_EXAMPLE).p_value


def test_zero_differences_are_dropped_and_switch_to_the_normal_approximation():
    result = wilcoxon_signed_rank([0.0, 0.0, *SCIPY_EXAMPLE])
    assert result.n == 15
    assert result.method == NORMAL
    assert result.p_value == pytest.approx(0.04088813291185591, rel=1e-9)


def test_ties_use_the_normal_approximation_with_the_tie_correction():
    differences = [0.1, 0.1, -0.1, 0.2, 0.3, 0.3, 0.4]
    result = wilcoxon_signed_rank(differences)
    assert result.method == NORMAL
    # |d| ranks: 0.1 x3 -> 2, 0.2 -> 4, 0.3 x2 -> 5.5, 0.4 -> 7; W+ = 2+2+4+5.5+5.5+7 = 26
    n = 7
    variance = n * (n + 1) * (2 * n + 1) / 24 - ((3**3 - 3) + (2**3 - 2)) / 48
    z = (26 - n * (n + 1) / 4) / math.sqrt(variance)
    assert result.statistic == 2.0
    assert result.p_value == pytest.approx(math.erfc(abs(z) / math.sqrt(2)), rel=1e-12)


def test_all_zero_differences_have_no_p_value():
    result = wilcoxon_signed_rank([0.0, 0.0, 0.0])
    assert (result.p_value, result.n, result.method) == (None, 0, UNDEFINED)


def test_exact_p_value_is_one_at_the_centre_of_the_distribution():
    # n = 3: W+ ranges 0..6, centre 3 (= ranks 1 + 2 against 3)
    assert wilcoxon_signed_rank([0.1, 0.2, -0.3]).p_value == 1.0


def test_smallest_exact_p_value_for_five_differences():
    # every difference positive: W+ = 15, p = 2 / 2**5
    assert wilcoxon_signed_rank([1, 2, 3, 4, 5]).p_value == pytest.approx(2 / 32)


def test_bootstrap_ci_reproduces_the_numpy_recipe_with_the_fixed_seed():
    values = [0.1, 0.4, 0.35, 0.8, 1.0, 0.0, 0.62]
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    sample = np.asarray(values)
    means = sample[rng.integers(0, len(values), size=(BOOTSTRAP_RESAMPLES, len(values)))].mean(1)
    expected = tuple(np.percentile(means, [2.5, 97.5]))
    assert bootstrap_mean_ci(values) == pytest.approx(expected, abs=0)


def test_bootstrap_ci_is_deterministic_and_brackets_the_mean():
    values = [0.2, 0.5, 0.9, 0.4, 0.6, 0.3]
    low, high = bootstrap_mean_ci(values)
    assert (low, high) == bootstrap_mean_ci(values)
    assert low <= sum(values) / len(values) <= high
    assert bootstrap_mean_ci(values, seed=7) != (low, high)


def test_bootstrap_ci_of_a_constant_sample_is_that_constant():
    assert bootstrap_mean_ci([0.5, 0.5, 0.5]) == (0.5, 0.5)


def test_bootstrap_ci_needs_a_value():
    with pytest.raises(ValueError):
        bootstrap_mean_ci([])
