# GitHub demo

Terraform for the `driftpilot-demo` org: two public repos (`demo-api`, `demo-web`), branch protection on
`demo-api`'s `main` (2 required approvals), and a `developers` team with `pull` access to `demo-api`.
Repos are public because branch protection on private repos needs a paid plan.

```bash
cd demo/github
export GITHUB_TOKEN=<fine-grained PAT for the org>   # Administration + Contents (repo), Members (org)
terraform init
terraform apply
terraform apply -refresh-only        # once after apply, see "First refresh" below
terraform plan -refresh-only -detailed-exitcode
```

State is local and gitignored for now. A real setup uses a remote backend with locking.

## Phase 0 findings (Terraform 1.17.0, integrations/github 6.13.0)

Recorded plan JSON is in `tests/fixtures/github/`.

| Case | Result | Fixture |
| --- | --- | --- |
| No change | exit 0, no drift | `control_no_change.json` |
| Required approvals 2 → 0 in the UI (scenario 2) | exit 2, `required_pull_request_reviews[0].required_approving_review_count: 2 -> 0` | `s2_required_approvals_reduced.json` |
| First refresh after `apply` | exit 2, noise only | `noise_provider_defaults_after_apply.json` |

- **First-refresh noise:** `force_push_bypassers`, `dismissal_restrictions`, `pull_request_bypassers` go `null → []`,
  and the team's `etag` changes. `etag` is an HTTP caching fingerprint, not configuration; it did not change on its
  own across later refreshes, but should always be ignored.
- **Revert works in place:** `terraform apply` restored approvals 0 → 2 as an in-place update.
