# Demo console

A local web page for presenting DriftPilot live. It is **not** part of the product: DriftPilot runs as a GitHub
Action. The console just makes the demo clickable.

```bash
uv pip install -e ".[demo]"                 # once (adds Streamlit)
streamlit run demo/console/app.py           # opens http://localhost:8501
```

Needs, on the presenter's machine: the demo org token (Keychain item `driftpilot-demo-pat` or `GITHUB_TOKEN`),
`gh` logged in, Docker running with the `demo/docker` stack applied, and optionally `GEMINI_API_KEY` in `.env`.
The sidebar shows which are present.

| Tab | What happens |
| --- | --- |
| 1 · Dangerous change | Sets `demo-api` approvals 2 → 0; the relay starts DriftPilot on GitHub; shows the run, its report and the critical issue |
| 2 · Good change | Adds a required status check; DriftPilot opens a verified codify pull request; shows its diff and proof |
| 3 · On my laptop | Changes a Docker container's memory, runs the DriftPilot engine locally, shows verdicts and the verified fix |
| 4 · History | The simulated 90-day dashboard |
| Reset | Undoes every scenario and closes open demo issues/PRs (never merges) |
