"""Pick pilot issues by a structural rule only (no agent outcomes, no API calls).

Rule (disclose it in the paper):
  - issue text names a gold-patch file ("strong" in localizability.csv)
  - gold patch touches exactly 1 file (localization success is well defined)
  - 100-400 words, at least 2 paragraphs
  - spread across repositories: round-robin over repos, fixed seed, max 3 per repo

Usage:
  python scripts/select_pilot_issues.py              # 20 issues
  python scripts/select_pilot_issues.py --n 12
Writes scripts/output/pilot_issue_ids.json and prints the ids.
"""
import argparse
import json
import random

import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--csv", default="scripts/output/localizability.csv")
ap.add_argument("--n", type=int, default=20)
ap.add_argument("--max-per-repo", type=int, default=3)
ap.add_argument("--seed", type=int, default=42)
ap.add_argument("--out", default="scripts/output/pilot_issue_ids.json")
a = ap.parse_args()

df = pd.read_csv(a.csv)
pool = df[(df.localizable == "strong") & (df.n_gold_files == 1)
          & df.words.between(100, 400) & (df.paragraphs >= 2)]
print(f"eligible: {len(pool)} of {len(df)}")
print(pool.groupby("repo").size().to_string(), "\n")

rng = random.Random(a.seed)
by_repo = {r: g.sort_values("issue_id").issue_id.tolist() for r, g in pool.groupby("repo")}
for ids in by_repo.values():
    rng.shuffle(ids)

picked, counts = [], {r: 0 for r in by_repo}
while len(picked) < a.n:
    progressed = False
    for r in sorted(by_repo):
        if len(picked) >= a.n:
            break
        if counts[r] < a.max_per_repo and counts[r] < len(by_repo[r]):
            picked.append(by_repo[r][counts[r]])
            counts[r] += 1
            progressed = True
    if not progressed:
        break

sel = df[df.issue_id.isin(picked)].sort_values("issue_id")
print(sel[["issue_id", "words", "gold_files"]].to_string(index=False))
with open(a.out, "w", encoding="utf-8") as f:
    json.dump(sorted(picked), f, indent=2)
print(f"\n{len(picked)} issues -> {a.out}")
