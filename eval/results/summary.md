# DriftPilot evaluation results

Generated 2026-10-25 06:37 UTC by `python eval/run_eval.py` · LLM: `gemini-3.1-flash-lite`

## Dataset

- **73 inputs** (aws.yaml 25, docker.yaml 7, github.yaml 18, noise.yaml 6, recorded.yaml 13, unmanaged.yaml 4); 13 recorded from the real demo, the rest hand-built.
- **135 labelled findings**: 72 real drift (20 critical), 63 noise.
- Labels follow SPEC §7 and the rubric in `eval/cases/README.md`, written before scoring.

## Results by setup

| Setup | Noise filtered | Real drift found | Severity right | Critical caught | Action right | False alarms | LLM calls | ~Tokens | Time |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| raw terraform | 0% | 94% | 0% | 0% | 0% | 100% | 0 | 0 | 0.0s |
| rules only | 98% | 100% | 19% | 45% | 19% | 2% | 0 | 0 | 0.3s |
| rules + local LLM | — | — | — | — | — | — | not run: skipped by choice: local model not installed (8 GB laptop); OllamaClient exists — set llm.provider: ollama to run it | | |
| rules + cloud LLM | 98% | 100% | 89% | 90% | 92% | 2% | 52 | 43,107 | 357.7s |
| cloud LLM without rules | 98% | 100% | 89% | 90% | 92% | 2% | 76 | 64,124 | 276.7s |

How to read it:

- *Noise filtered*: share of not-real findings hidden.
- *Real drift found*: share of real drift reported (raw Terraform misses unmanaged).
- *Severity right* / *Action right*: over real drift only.
- *Critical caught*: critical findings rated critical.
- *False alarms*: noise reported as drift.
- *LLM calls* include cached answers; *Time* is with the cache warm.

## Prompt stability

`rules + cloud LLM` run 5 times on 12 inputs (12 LLM-judged findings): **100%** got the same severity and action every time.

## Analytics on simulated history (planted patterns)

| Planted | Result |
| --- | --- |
| Drift spike on 2026-09-25 | ✅ found as top unusual day; ✅ found as change-point |
| `docker_container.app3` `memory` recurring | ✅ found |
| Human overrule rise | ✅ found (13% → 61%) |

## Measured in live runs (demo environments)

| Metric | Result | Where |
| --- | --- | --- |
| Codify verification (GitHub, scenario 5) | verified on attempt 1, plan proof "No changes" | PR driftpilot-demo/infra#1 |
| Codify verification (Docker, memory) | verified on attempt 1 with Flash-Lite (3.5 Flash: attempt 3) | local runs, Phase 2 |
| Import verification (Docker container) | correctly **rejected**: provider forces replacement (`env`) | local run, Phase 2 |
| Time to detect, event-driven (relay) | 10–18 s from the change to the run starting | infra runs, Phases 1–2 |
| Time to detect, scheduled | ≤ 6 h (cron `17 */6 * * *`) | infra workflow |
| Cost per run | free tier (Gemini Flash-Lite); calls and tokens per setup are above | |
