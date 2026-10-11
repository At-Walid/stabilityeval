"""Free check (no API calls): can the agent find the right file from the issue text alone?

The LLM Baseline never sees the repository. Localization success is only
possible when the issue text itself points at the gold-patch files. This
script measures that for SWE-bench Lite, using the hidden gold patch only to
CLASSIFY issues (never shown to any agent).

  strong : issue text names a gold file (full path, basename with extension,
           or dotted module path such as sympy.core.mod)
  weak   : text names no gold file but mentions a function/class that the gold
           patch modifies (taken from the hunk headers)
  none   : neither

Usage:
  python scripts\localizability.py
  python scripts\localizability.py --candidates scripts\output\stage1_candidates.json
  python scripts\localizability.py --dataset-json data\swebench_lite_issues.json   (offline)
Writes scripts/output/localizability.csv
"""
import argparse
import json
import os
import re

import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--candidates", default="scripts/output/stage1_candidates.json")
ap.add_argument("--dataset-json", default=None)
ap.add_argument("--out", default="scripts/output/localizability.csv")
args = ap.parse_args()


def load_instances():
    if args.dataset_json:
        with open(args.dataset_json, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "issues" in data:  # the bundled data/swebench_lite_issues.json
            return [{"instance_id": i["id"], "repo": i["repo"], "patch": i["gold_patch"],
                     "problem_statement": i["problem_statement"]} for i in data["issues"]]
        return data
    from datasets import load_dataset
    ds = load_dataset("princeton-nlp/SWE-bench_Lite", split="test")
    return [dict(r) for r in ds]


def gold_files(patch):
    return sorted(set(re.findall(r"^diff --git a/(\S+) b/\S+", patch, re.M)))


def gold_symbols(patch):
    syms = set()
    for h in re.findall(r"^@@[^@]*@@\s*(.*)$", patch, re.M):
        m = re.search(r"(?:def|class)\s+([A-Za-z_]\w+)", h)
        if m and len(m.group(1)) >= 5:
            syms.add(m.group(1))
    return sorted(syms)


def classify(text, patch):
    files = gold_files(patch)
    for p in files:
        base = os.path.basename(p)
        dotted = p[:-3].replace("/", ".") if p.endswith(".py") else None
        if p in text or base in text or (dotted and dotted.count(".") >= 1 and dotted in text):
            return "strong", files
    for s in gold_symbols(patch):
        if re.search(r"\b" + re.escape(s) + r"\b", text):
            return "weak", files
    return "none", files


rows = []
for r in load_instances():
    text = r["problem_statement"]
    level, files = classify(text, r["patch"])
    rows.append({
        "issue_id": r["instance_id"], "repo": r["repo"], "localizable": level,
        "n_gold_files": len(files), "gold_files": ";".join(files),
        "words": len(text.split()),
        "paragraphs": len([p for p in re.split(r"\n\s*\n", text) if p.strip()]),
    })
df = pd.DataFrame(rows)
os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
df.to_csv(args.out, index=False)

print(f"{len(df)} issues analysed\n")
print("All issues:", df.localizable.value_counts().to_dict())
band = df[(df.words.between(100, 400)) & (df.paragraphs >= 2)]
print("With 100-400 words and >=2 paragraphs:", band.localizable.value_counts().to_dict())
print("\nStrongly localizable, per repository (all / in the word band):")
for repo, g in df[df.localizable == "strong"].groupby("repo"):
    inband = int(((g.words.between(100, 400)) & (g.paragraphs >= 2)).sum())
    print(f"  {repo:<34} {len(g):>3} / {inband:>3}")

if os.path.exists(args.candidates):
    with open(args.candidates, encoding="utf-8") as f:
        cand = json.load(f)
    ids = [c.get("issue_id") or c.get("instance_id") or c.get("id") for c in cand]
    c = df[df.issue_id.isin(ids)]
    print(f"\nYour {len(c)} Stage 1 candidates:", c.localizable.value_counts().to_dict())
    print(c[["issue_id", "localizable", "gold_files"]].to_string(index=False))
print(f"\nWrote {args.out}")
