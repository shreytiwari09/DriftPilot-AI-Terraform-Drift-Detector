# Evaluation cases

A fixed, labelled test set. Every case is one drift **input** (a recorded plan, inline drift, or an unmanaged
resource) plus the **expected verdict** for each finding it produces. `eval/run_eval.py` runs DriftPilot in several
configurations over these cases and scores the results.

Labels were written from SPEC §7 and the rubric below **before** any configuration was scored. They are not edited to
match model output. Changing a label or adding a case means re-running every configuration.

## Files

| File | What |
| --- | --- |
| `recorded.yaml` | Plans recorded from the real demo environments (GitHub org and local Docker) |
| `github.yaml` | Variants of the GitHub scenarios (other values, increases vs decreases, other settings) |
| `docker.yaml` | Variants of the Docker scenarios |
| `aws.yaml` | AWS-style resources (security groups, S3, IAM, instances, databases), hand-built plan JSON |
| `noise.yaml` | Changes that are not real drift |
| `unmanaged.yaml` | Resources created outside Terraform |

## Case format

```yaml
- id: unique-id
  source: recorded | synthetic
  scenario: 2                      # SPEC §7 scenario number, if any
  fixture: github/s2_required_approvals_reduced   # a plan in tests/fixtures/, or:
  drift:                           # inline resource_drift entries
    - address: aws_security_group.admin
      before: {...}
      after: {...}
      actions: [update]            # default; [delete] for a deleted resource
  unmanaged: {provider: github, kind: repository, name: demo-x}   # or an unmanaged resource
  code_dir: demo/github            # where the resource's Terraform code is (context for the LLM)
  code: |                          # or the code inline
    resource "..." "..." { ... }
  default: noise                   # label for findings not listed in expect (only for noise-only inputs)
  expect:
    - attribute: required_pull_request_reviews[0].required_approving_review_count
      address: ...                 # needed when the input has more than one resource
      real: true
      severity: critical
      action: [revert]             # every acceptable action
```

## Labelling rubric

**Real drift?** No (`real: false`) for: provider-filled defaults (null → empty/zero), API metadata (etag), runtime
data (IPs, MACs, exit codes, the ports list of a stopped container), list reorders with the same members, and JSON
documents equal after normalisation. Everything a person changed is real.

**Severity**
- `critical` — a security control removed or weakened: protection deleted, required reviews lowered, admin ports or
  data opened to the internet, encryption or security alerts turned off, wildcard admin permissions.
- `high` — privilege escalation, data or availability at risk: admin/write access granted, resource deleted,
  repository archived, container stopped, backups or deletion protection reduced.
- `medium` — functional configuration: resource limits, restart policies, status checks, features on/off,
  stricter-than-code security settings, instance sizes; unmanaged resources (policy).
- `low` — cosmetic or descriptive: descriptions, topics, tags, homepages.
- `none` — not real drift.

**Action** (all reasonable answers are accepted)
- weakening or risky changes → `revert` (plus `investigate` where intent is unclear)
- deliberate improvements / harmless metadata → `codify` (plus `ignore_changes` for labels that change often)
- deleted resources → `recreate`
- unmanaged resources → `import`
- not real → `none`
