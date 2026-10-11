from __future__ import annotations

import random

import pytest

from stableagent.metrics.patch_similarity import (
    c1_similarity,
    extract_final_patch,
    has_unified_diff,
)

PATCH = (
    "--- a/foo.py\n+++ b/foo.py\n@@ -1,3 +1,3 @@\n"
    " def f(x):\n-    return x + 1\n+    return x + 2\n"
)


def test_identical_patches_score_one():
    assert c1_similarity(PATCH, PATCH) == 1.0


def test_unrelated_patches_score_low():
    assert c1_similarity("aaaaaaaaaa", "zzzzzzzzzz") == 0.0


def test_is_symmetric_for_simple_inputs():
    other = PATCH.replace("x + 2", "x * 2")
    assert c1_similarity(PATCH, other) == pytest.approx(c1_similarity(other, PATCH))


def test_value_is_in_unit_interval_and_between_extremes():
    other = PATCH.replace("x + 2", "x * 2")
    assert 0.0 < c1_similarity(PATCH, other) < 1.0


def test_none_is_treated_as_empty():
    assert c1_similarity(None, None) == 1.0
    assert c1_similarity(None, PATCH) == 0.0
    assert c1_similarity(PATCH, None) == 0.0
    assert c1_similarity("", PATCH) == 0.0


def test_line_endings_and_outer_whitespace_do_not_count_as_change():
    crlf = PATCH.replace("\n", "\r\n")
    assert c1_similarity(PATCH, crlf) == 1.0
    assert c1_similarity(PATCH, "\n\n" + PATCH + "\n\n") == 1.0


def test_long_near_identical_patches_are_not_collapsed_by_autojunk():
    """Regression guard: difflib's default autojunk=True scores ~0.0 for 200+ char
    strings built from a small alphabet, even when they are ~85% identical."""
    rng = random.Random(1)
    alphabet = "abcdefghijklmnopqrstuvwxyz ABCDEFGHIJ\n+-@(){}_.=,:0123456789"
    a = "".join(rng.choice(alphabet) for _ in range(3000))
    b = "".join(c if rng.random() > 0.15 else rng.choice(alphabet) for c in a)
    assert c1_similarity(a, b) > 0.7


# ---------------------------------------------------------------------------
# has_unified_diff / extract_final_patch
#
# Replies modelled on what the LLM Baseline really returns: prose first, "<br>" artefacts,
# fenced diffs, and several drafts of the same file.
# ---------------------------------------------------------------------------


def _diff(path: str, old: str, new: str) -> str:
    return f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-{old}\n+{new}"


def _fenced(diff: str) -> str:
    return f"```diff\n{diff}\n```"


def test_has_unified_diff():
    assert has_unified_diff(PATCH)
    assert has_unified_diff("Here:\n" + _fenced(PATCH))
    assert not has_unified_diff("I need to see the repository first.")
    assert not has_unified_diff("--- a/foo.py\n+++ b/foo.py\n")  # headers but no hunk
    assert not has_unified_diff(None)
    assert not has_unified_diff("")


def test_extract_strips_prose_artefacts_and_fences():
    reply = (
        "Looking at the issue, the problem is in `f`.\n\n<br>\n\n"
        + _fenced(_diff("a.py", "x = 1", "x = 2"))
        + "\n\nThis fixes it."
    )
    assert extract_final_patch(reply) == _diff("a.py", "x = 1", "x = 2")


def test_same_diff_with_different_prose_extracts_identically():
    diff = _diff("a.py", "x = 1", "x = 2")
    first = "Let me look.\n\n" + _fenced(diff)
    second = "The bug is obvious, so:\n\n<br>\n\n" + _fenced(diff) + "\n\nDone."
    assert extract_final_patch(first) == extract_final_patch(second)
    assert c1_similarity(first, second) < 1.0  # the raw replies differ ...
    assert c1_similarity(extract_final_patch(first), extract_final_patch(second)) == 1.0


def test_only_the_last_draft_of_a_file_is_kept():
    reply = (
        _fenced(_diff("a.py", "x = 1", "x = 2"))
        + "\n\nThis is getting messy. A cleaner diff:\n\n"
        + _fenced(_diff("a.py", "x = 1", "x = 3"))
    )
    assert extract_final_patch(reply) == _diff("a.py", "x = 1", "x = 3")


def test_distinct_files_are_all_kept_in_first_appearance_order_with_their_final_version():
    reply = "\n".join(
        [
            _fenced(_diff("a.py", "a = 1", "a = 2")),
            _fenced(_diff("b.py", "b = 1", "b = 2")),
            _fenced(_diff("a.py", "a = 1", "a = 9")),  # revises a.py again
        ]
    )
    assert extract_final_patch(reply) == (
        _diff("a.py", "a = 1", "a = 9") + "\n" + _diff("b.py", "b = 1", "b = 2")
    )


def test_a_revised_file_inside_a_multi_file_block_does_not_leave_its_stale_version():
    two_files = _diff("a.py", "a = 1", "a = 2") + "\n" + _diff("b.py", "b = 1", "b = 2")
    reply = _fenced(two_files) + "\nRevised b.py:\n" + _fenced(_diff("b.py", "b = 1", "b = 7"))
    patch = extract_final_patch(reply)
    assert "a = 2" in patch and "b = 7" in patch
    assert "b = 2" not in patch


def test_a_reply_cut_off_before_the_closing_fence_still_yields_its_patch():
    truncated = "Here is the fix:\n\n```diff\n" + _diff(
        "a.py", "x = 1", "x = 2"
    )  # no closing fence
    assert extract_final_patch(truncated) == _diff("a.py", "x = 1", "x = 2")


def test_non_diff_code_fences_are_ignored():
    reply = "Idea:\n```python\nx = 2\n```\n" + _fenced(_diff("a.py", "x = 1", "x = 2"))
    assert extract_final_patch(reply) == _diff("a.py", "x = 1", "x = 2")


def test_unfenced_diff_is_taken_from_the_first_file_header():
    reply = "Sure, here you go:\n\n" + PATCH
    assert extract_final_patch(reply) == PATCH.strip()


def test_tag_wrapped_drafts_without_fences_keep_only_the_last_one():
    # Real replies sometimes wrap diffs in <patch> tags instead of a markdown fence.
    first = _diff("a.py", "x = 1", "x = 2")
    last = _diff("a.py", "x = 1", "x = 3")
    reply = (
        f"Looking at this issue...\n\n<patch>\n{first}\n</patch>\n\n"
        f"Actually, a cleaner version:\n\n<patch>\n{last}\n</patch>"
    )
    assert extract_final_patch(reply) == last


def test_trailing_prose_and_closing_tags_are_trimmed_from_an_unfenced_diff():
    diff = _diff("a.py", "x = 1", "x = 2")
    assert extract_final_patch(f"Here:\n\n{diff}\n</patch>\n\nThis fixes the bug.") == diff


def test_unfenced_multi_file_diff_keeps_every_file_and_trims_the_tail():
    a, b = _diff("a.py", "a = 1", "a = 2"), _diff("b.py", "b = 1", "b = 2")
    assert extract_final_patch(f"Fix:\n{a}\n{b}\nDone.") == f"{a}\n{b}"


def test_a_reply_without_any_diff_falls_back_to_the_stripped_text():
    assert extract_final_patch("  I need the repository first.  ") == "I need the repository first."


def test_empty_replies_extract_to_an_empty_patch():
    assert extract_final_patch(None) == ""
    assert extract_final_patch("") == ""


def test_new_file_diffs_are_keyed_by_their_target_path():
    created = "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+x = 1"
    other = "--- /dev/null\n+++ b/other.py\n@@ -0,0 +1 @@\n+y = 1"
    patch = extract_final_patch(_fenced(created) + "\n" + _fenced(other))
    assert "+x = 1" in patch and "+y = 1" in patch  # two new files must not overwrite each other


def test_crlf_replies_are_normalised():
    reply = ("Fix:\n" + _fenced(PATCH.strip())).replace("\n", "\r\n")
    assert extract_final_patch(reply) == PATCH.strip()
