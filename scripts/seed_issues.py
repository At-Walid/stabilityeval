"""Insert the 5 demo issues covered by the committed MockReplay fixtures into the database.

The issues are read verbatim, with their hidden gold patches, from the bundled dataset file
data/swebench_lite_issues.json (offline). Idempotent: an issue already present keeps its text.
The dashboard's "Load SWE-bench Lite" button imports all 300 bundled issues the same way.

Usage:
    python scripts/seed_issues.py
"""
from __future__ import annotations

from stability_eval.dashboard._db import DEMO_ISSUE_IDS, insert_demo_issues


def main() -> None:
    summary = insert_demo_issues()
    print(
        f"{summary.inserted} inserted, {summary.updated} already present "
        f"({len(DEMO_ISSUE_IDS)} demo issues: {', '.join(DEMO_ISSUE_IDS)})"
    )
    if summary.kept_text:
        print("Kept their existing (non-verbatim) text: " + ", ".join(summary.kept_text))


if __name__ == "__main__":
    main()
