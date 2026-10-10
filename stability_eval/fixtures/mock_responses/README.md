# Mock response fixtures

This directory contains pre-recorded AgentOutput JSON files used by the
MockReplay adapter. Fixtures are committed to the repository so that any
contributor can run the full demo pipeline without an API key.

## Naming convention

    {issue_id}__{transformation_name}__mock_replay.json

Example:

    psf__requests-2317__reordering__mock_replay.json

SWE-bench issue ids contain `__` themselves; transformation names never do. An
issue is replayable for a set of transformations when a fixture exists for its
`original` and for each of them.

## File schema

```json
{
  "status": "success",
  "patch": "--- a/...\n+++ b/...\n...",
  "explanation": "Optional explanation string",
  "token_usage": { "input": 1234, "output": 567 },
  "cost_usd": 0.08,
  "runtime_seconds": 3.2,
  "error_message": null,
  "raw_logs": "",
  "metadata": {}
}
```

Fixtures recorded from an experiment add:

- `control_repeats` (original fixtures only): the outputs of the issue's control
  runs (re-runs of the unchanged original), replayed in order by the runner's
  control runs, so the noise floor is replayed too;
- `variant` (variant fixtures only): the issue text the run used, its params and
  provenance (generator, transform_version, mode, quality warning, no-op,
  exclusion reason) and a hash of the original text. On a cache miss, mock mode
  restores it into the transformation cache instead of a placeholder, so a fresh
  database replays on the very same variants;
- `recorded_from`: the experiment and run it was recorded from.

A cell the runner skipped (an excluded or no-op variant) is recorded with status
`skipped_variant`. The gold patch is never recorded.

## Recording an experiment

```bash
stabilityeval record-fixtures --experiment-id <experiment uuid>
```

One fixture per issue and variant; recording again rewrites identical files.
Replay it with the experiment's config and `--mode mock`
(`stabilityeval run --config configs/icse_pilot.json --mode mock`): every run and
every metric comes back identical. The ICSE pilot (experiment
`bc6f1372-2088-45dd-907c-d741c0545d27`, 20 issues) is recorded here.
