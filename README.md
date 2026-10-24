# DriftPilot

DriftPilot is a GitHub Action and Python CLI that detects Terraform infrastructure drift — changes made to real
infrastructure outside Terraform — separates real drift from noise, and reports it.

> Work in progress (v0.1). Triage with an LLM, verified fix PRs and drift analytics are coming.

## Quick start (CLI)

```bash
pip install -e ".[dev]"
driftpilot scan --dir demo/docker
driftpilot scan --dir demo/docker --json
```

## As a GitHub Action

```yaml
- uses: hashicorp/setup-terraform@v3
  with:
    terraform_wrapper: false
- uses: shreytiwari09/DriftPilot-AI-Terraform-Drift-Detector@v0.1.0
  with:
    working-directory: infra/
    provider-token: ${{ secrets.INFRA_GITHUB_TOKEN }}
```

Drift findings appear in the job summary.
