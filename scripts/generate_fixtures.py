"""Generate MockReplay fixtures for the 5 pre-loaded SWE-bench Lite sample issues.

Produces one JSON file per (issue, transformation variant) combination, named
`{issue_id}__{variant}__mock_replay.json`, matching the schema consumed by
`MockReplayAdapter` (see stability_eval/agents/mock_replay.py) and documented
in docs/SPEC.md section 10.3 / Appendix A.

5 issues x 7 variants = 35 fixtures. The success/failure pattern and all
random ranges are hardcoded; random.Random(42) makes the output byte-for-byte
reproducible across runs.

Usage:
    python scripts/generate_fixtures.py
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "stability_eval" / "fixtures" / "mock_responses"

VARIANTS = [
    "original",
    "paraphrase",
    "verbosity_reduction",
    "typo_injection",
    "reordering",
    "paragraph_to_structured",
    "neutralize_emotional",
]

# ---------------------------------------------------------------------------
# Issue fixtures: one realistic unified diff + one-sentence explanation each.
# ---------------------------------------------------------------------------

ISSUES: dict[str, dict[str, str]] = {
    "django__django-11099": {
        "explanation": (
            "Replaced the trailing `$` anchor with `\\Z` in the username validator regexes "
            "so a trailing newline is no longer accepted."
        ),
        "patch": (
            "--- a/django/contrib/auth/validators.py\n"
            "+++ b/django/contrib/auth/validators.py\n"
            "@@ -7,7 +7,7 @@ class ASCIIUsernameValidator(validators.RegexValidator):\n"
            "-    regex = r'^[\\w.@+-]+$'\n"
            "+    regex = r'^[\\w.@+-]+\\Z'\n"
            "     message = _(\n"
            "         'Enter a valid username. This value may contain only English letters, '\n"
            "         'numbers, and @/./+/-/_ characters.'\n"
            "     )\n"
            "@@ -16,7 +16,7 @@ class UnicodeUsernameValidator(validators.RegexValidator):\n"
            "-    regex = r'^[\\w.@+-]+$'\n"
            "+    regex = r'^[\\w.@+-]+\\Z'\n"
            "     message = _(\n"
            "         'Enter a valid username. This value may contain only letters, '\n"
            "         'numbers, and @/./+/-/_ characters.'\n"
            "     )\n"
        ),
    },
    "django__django-12125": {
        "explanation": (
            "Used `__qualname__` instead of `__name__` when serializing bound methods of inner "
            "classes so migrations reference the correct nested path."
        ),
        "patch": (
            "--- a/django/db/migrations/serializer.py\n"
            "+++ b/django/db/migrations/serializer.py\n"
            "@@ -168,9 +168,9 @@ class FunctionTypeSerializer(BaseSerializer):\n"
            "         if getattr(self.value, \"__self__\", None) and isinstance(\n"
            "             self.value.__self__, type\n"
            "         ):\n"
            "             klass = self.value.__self__\n"
            "-            module = klass.__module__\n"
            "-            return \"%s.%s.%s\" % (module, klass.__name__, self.value.__name__), {\n"
            "-                \"import %s\" % module\n"
            "-            }\n"
            "+            module = klass.__module__\n"
            "+            qualname = \"%s.%s\" % (klass.__qualname__, self.value.__name__)\n"
            "+            return \"%s.%s\" % (module, qualname), {\"import %s\" % module}\n"
            "         # Further error checking\n"
        ),
    },
    "astropy__astropy-6938": {
        "explanation": (
            "Added a fallback that converts the Fortran `D` exponent to `E` before parsing so "
            "FITS float values in D-exponent notation no longer raise ValueError."
        ),
        "patch": (
            "--- a/astropy/io/ascii/fastbasic.py\n"
            "+++ b/astropy/io/ascii/fastbasic.py\n"
            "@@ -212,7 +212,10 @@ class FastBasic:\n"
            "     def _convert_value(self, value):\n"
            "-        return float(value)\n"
            "+        try:\n"
            "+            return float(value)\n"
            "+        except ValueError:\n"
            "+            return float(value.replace('D', 'E').replace('d', 'e'))\n"
        ),
    },
    "sympy__sympy-20590": {
        "explanation": (
            "Captured each symbol's assumptions before trigonometric simplification and "
            "restored them afterward so downstream simplifications stay correct."
        ),
        "patch": (
            "--- a/sympy/simplify/simplify.py\n"
            "+++ b/sympy/simplify/simplify.py\n"
            "@@ -589,7 +589,11 @@ def simplify(expr, **kwargs):\n"
            "-    expr = trigsimp(expr, deep=True)\n"
            "+    original_assumptions = expr.assumptions0\n"
            "+    expr = trigsimp(expr, deep=True)\n"
            "+    if original_assumptions:\n"
            "+        expr = expr.subs(\n"
            "+            [(s, s.func(s.name, **original_assumptions)) for s in expr.free_symbols]\n"
            "+        )\n"
        ),
    },
    "matplotlib__matplotlib-23299": {
        "explanation": (
            "Guarded `bar()` against all-NaN height arrays by defaulting `bottom` to a "
            "zero array instead of calling `np.isnan` on an incompatible type."
        ),
        "patch": (
            "--- a/lib/matplotlib/axes/_axes.py\n"
            "+++ b/lib/matplotlib/axes/_axes.py\n"
            "@@ -2438,7 +2438,10 @@ def bar(self, x, height, width=0.8, bottom=None, *, align=\"center\", **kwargs):\n"
            "-    if bottom is None:\n"
            "-        bottom = 0\n"
            "+    if bottom is None:\n"
            "+        if np.all(np.isnan(height)):\n"
            "+            bottom = np.zeros_like(height)\n"
            "+        else:\n"
            "+            bottom = 0\n"
        ),
    },
}

# ---------------------------------------------------------------------------
# Hardcoded success/failure matrix (5 issues x 7 variants)
# ---------------------------------------------------------------------------

FAILURES: set[tuple[str, str]] = {
    ("sympy__sympy-20590", "reordering"),
    ("matplotlib__matplotlib-23299", "typo_injection"),
    ("astropy__astropy-6938", "paragraph_to_structured"),
    ("sympy__sympy-20590", "paragraph_to_structured"),
    ("astropy__astropy-6938", "verbosity_reduction"),
    ("sympy__sympy-20590", "verbosity_reduction"),
    ("matplotlib__matplotlib-23299", "verbosity_reduction"),
}

ERROR_MESSAGES = [
    "Agent could not identify the relevant code from the compressed issue description.",
    "Insufficient context in the issue description to locate the bug.",
    "Issue description too brief to determine the correct file to modify.",
]

_HUNK_RE = re.compile(r"^@@ -(\d+),(\d+) \+(\d+),(\d+) @@(.*)$", re.MULTILINE)


def _shift_hunks(patch: str, offset: int) -> str:
    """Shift every hunk's start line numbers by *offset*, keeping counts and content."""

    def repl(m: re.Match[str]) -> str:
        old_start, old_count, new_start, new_count, rest = m.groups()
        return f"@@ -{int(old_start) + offset},{old_count} +{int(new_start) + offset},{new_count} @@{rest}"

    return _HUNK_RE.sub(repl, patch)


def _add_context_line(patch: str) -> str:
    """Insert one extra blank context line into the first hunk and bump its counts."""
    lines = patch.split("\n")
    hunk_idx = next((i for i, ln in enumerate(lines) if ln.startswith("@@")), None)
    if hunk_idx is None:
        return patch

    m = _HUNK_RE.match(lines[hunk_idx])
    if not m:
        return patch

    old_start, old_count, new_start, new_count, rest = m.groups()
    lines[hunk_idx] = (
        f"@@ -{old_start},{int(old_count) + 1} +{new_start},{int(new_count) + 1} @@{rest}"
    )

    insert_at = len(lines)
    for j in range(hunk_idx + 1, len(lines)):
        if lines[j].startswith("@@") or lines[j].startswith("---") or lines[j] == "":
            insert_at = j
            break
    lines.insert(insert_at, " ")
    return "\n".join(lines)


def _make_variant_patch(base_patch: str, variant: str, rng: random.Random) -> str:
    if variant == "original":
        return base_patch
    if variant == "verbosity_reduction":
        # Same file, slightly different hunk/line numbers than the original.
        return _shift_hunks(base_patch, rng.randint(3, 12))
    # paraphrase / neutralize_emotional / reordering / typo_injection /
    # paragraph_to_structured: nearly identical, maybe +/-1 context line.
    if rng.random() < 0.5:
        return _add_context_line(base_patch)
    return base_patch


def _raw_log(issue_id: str, variant: str, status: str, runtime: float) -> str:
    ts = "2026-07-05T09:00:00Z"
    lines = [
        f"[{ts}] INFO  agent='mock_replay' issue={issue_id} transform='{variant}'",
        f"[{ts}] INFO  Loading fixture from disk",
        f"[{ts}] INFO  Fixture deserialized (issue_id={issue_id}, transform={variant})",
    ]
    if status == "success":
        lines.append(f"[{ts}] INFO  Patch extracted successfully (runtime={runtime:.2f}s)")
        lines.append(f"[{ts}] INFO  Status: SUCCESS")
    else:
        lines.append(f"[{ts}] WARN  Patch extraction failed — response did not contain a valid diff")
        lines.append(f"[{ts}] ERROR Status: FAILURE (runtime={runtime:.2f}s)")
    return "\n".join(lines)


def _metadata(issue_id: str, variant: str) -> dict:
    return {
        "issue_id": issue_id,
        "transformation_name": variant,
        "agent": "mock_replay",
        "fixture_version": "1.0",
    }


def build_fixtures() -> dict[str, dict]:
    """Return {filename: fixture_dict}, fully deterministic given random.Random(42)."""
    rng = random.Random(42)
    fixtures: dict[str, dict] = {}

    for issue_id, info in ISSUES.items():
        for variant in VARIANTS:
            filename = f"{issue_id}__{variant}__mock_replay.json"
            is_failure = (issue_id, variant) in FAILURES

            if is_failure:
                token_in = rng.randint(1800, 2800)
                token_out = rng.randint(50, 200)
                runtime = round(rng.uniform(0.8, 2.1), 2)
                # cost_usd is always 0.0 for MockReplay fixtures: per SPEC section 12.2,
                # mock mode never calls a real API and must cost $0, regardless of the
                # token counts recorded for display purposes.
                data = {
                    "status": "failure",
                    "patch": None,
                    "explanation": None,
                    "token_usage": {"input": token_in, "output": token_out},
                    "cost_usd": 0.0,
                    "runtime_seconds": runtime,
                    "error_message": rng.choice(ERROR_MESSAGES),
                    "raw_logs": _raw_log(issue_id, variant, "failure", runtime),
                    "metadata": _metadata(issue_id, variant),
                }
            else:
                token_in = rng.randint(1800, 2800)
                token_out = rng.randint(400, 1200)
                runtime = round(rng.uniform(2.1, 8.4), 2)
                patch = _make_variant_patch(info["patch"], variant, rng)
                data = {
                    "status": "success",
                    "patch": patch,
                    "explanation": info["explanation"],
                    "token_usage": {"input": token_in, "output": token_out},
                    "cost_usd": 0.0,
                    "runtime_seconds": runtime,
                    "error_message": None,
                    "raw_logs": _raw_log(issue_id, variant, "success", runtime),
                    "metadata": _metadata(issue_id, variant),
                }

            fixtures[filename] = data

    return fixtures


def main() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    fixtures = build_fixtures()
    for filename, data in fixtures.items():
        (FIXTURES_DIR / filename).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(fixtures)} fixture files to {FIXTURES_DIR}")


if __name__ == "__main__":
    main()
