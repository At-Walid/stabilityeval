# Public demo on Streamlit Community Cloud

The public demo runs the GUI in replay mode: no API key, no secrets, no paid call. Everything it
needs is in the repository:

- `requirements.txt` at the repository root: the pinned dependencies, installed by Streamlit
  Community Cloud;
- `.streamlit/config.toml`: no usage statistics, minimal toolbar;
- `stability_eval/dashboard/StabilityEval.py`: the entry point. It adds the repository root to
  `sys.path` itself, so the package does not need to be installed;
- `data/pilot/stabilityeval_pilot.db`: on first start, the app creates its database
  (`stabilityeval.db` in the working directory) as a copy of this file, so the 300 SWE-bench Lite
  issues and the recorded pilot are there at once.

## Deploy

1. Push the public repository to GitHub (see the release commands) and make it public.
2. Go to https://share.streamlit.io and sign in with the GitHub account that owns the repository.
3. Click **Create app**, then choose to deploy a public app from GitHub.
4. Fill in:
   - Repository: `At-Walid/stabilityeval`
   - Branch: the default branch of the public repository
   - Main file path: `stability_eval/dashboard/StabilityEval.py`
   - App URL: for example `stabilityeval` (gives `https://stabilityeval.streamlit.app`)
5. Open **Advanced settings**: choose **Python 3.11**. Leave **Secrets** empty: do not add an
   `ANTHROPIC_API_KEY`, or every visitor could spend it.
6. Click **Deploy**. The first build installs the dependencies and takes a few minutes.
7. Check the app: section A shows "300 loaded, 25 replayable, 20 ICSE pilot";
   *Past Experiments* lists `icse_pilot_v1`; its RQ1 tab shows "Originals localized: 20 of 20" and
   "107 of 108", its RQ2 tab a repeat similarity of 0.754 and a paraphrase similarity of 0.541.
8. Put the app URL in `README.md` (the "Public demo: TODO" line).

## Behaviour to expect

- The app's file system is not persistent: when the app restarts or goes to sleep after a period
  without visitors, the database starts again from the pilot copy. Replays run by visitors are
  lost then; nothing else is.
- All visitors share one database while the app is up, so a replay run by one visitor appears in
  everyone's *Past Experiments* list.
- A visitor may choose *LLM Baseline* and paste their own API key; it stays in their browser
  session and is never written to disk, the database or the logs. Without a key, the Run button
  stays disabled in that mode.
