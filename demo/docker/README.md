# Docker demo

Local, zero-cost Terraform setup used by the CLI demo and as a drift sandbox.
Manages one network, one volume, and two containers (`web` = nginx, `cache` = redis), all labelled `managed-by=terraform`.

```bash
cd demo/docker
terraform init
terraform apply                      # creates everything in local Docker
terraform apply -refresh-only        # see "First refresh" below — run once after apply
terraform plan -refresh-only -detailed-exitcode
terraform destroy
```

State (`terraform.tfstate`) is local and gitignored.

## Phase 0 findings (Terraform 1.17.0, kreuzwerker/docker 4.6.x)

Recorded plan JSON for each case is in `tests/fixtures/docker/`.

### Exit codes of `plan -refresh-only -detailed-exitcode`

| Situation | Exit code |
| --- | --- |
| No drift | 0 |
| Drift found | 2 |
| Error | 1 |

Same as a normal plan, so SPEC §4.1 holds.

### Scenarios

| Scenario | Manual change | Seen in `resource_drift`? | Attributes changed | Fixture |
| --- | --- | --- | --- | --- |
| 11 | `docker update --memory 512m --memory-swap 1g` | yes, `update` | `memory`, `memory_swap` | `s11_memory_changed.json` |
| 12 | `docker update --restart on-failure:3` | yes, `update` | `restart`, `max_retry_count` | `s12_restart_policy_changed.json` |
| 10 | `docker rm -f` the cache container | yes, `delete` (no before/after diff) | — | `s10_container_removed.json` |
| 13 | `docker run` with the managed label | **no** (plan exit 0) — only visible to a scanner | — | `s13_state_for_scanner.json` (state to diff against `docker ps`) |
| extra | `docker update --cpu-shares 512` | yes, `update` | `cpu_shares` | `extra_cpu_shares_changed.json` |
| extra | `docker stop` | yes, `update` | `must_run`, `exit_code`, `ports`, `network_data[*]` | `extra_container_stopped.json` |
| 14 | none (control) | no, exit 0 | — | `control_no_change.json` |

All four planned Docker scenarios (10–13) work as the spec describes; none need replacing.

### Attributes re-read on refresh

Detected: `memory`, `memory_swap`, `restart`, `max_retry_count`, `cpu_shares`, `must_run` (container stopped),
`ports`, `network_data`, container existence.
Not changeable after creation with `docker update` (so not useful hand-drift scenarios): image, env, labels, mounts.

### Noise to filter (rule-pack candidates)

- **First refresh after `apply`:** every container, network and volume reports `null → []` / `null → {}` on
  attributes like `dns`, `sysctls`, `log_opts`, `tmpfs`, `driver_opts`, `ipam_options`, `networks_advanced[*].gw_priority`.
  Nothing really changed; the provider fills in empty defaults. Fixture: `noise_provider_defaults_after_apply.json`.
- **`network_data[*]`** (IP, gateway, MAC) is runtime data; the MAC changes on every restart.
  Fixture: `noise_mac_address_after_restart.json`.

### Gotchas

- Docker sets `memory_swap` to 2× `memory` when it isn't given. Without `memory_swap` in the code, every normal
  `plan` wants to change it, which would break the "zero-change plan" verification. `main.tf` sets it explicitly.
- `cpu_shares` cannot be reverted in place: Docker treats `--cpu-shares 0` as "leave unchanged", and the provider's
  in-place update has the same limitation, so `terraform apply` reports success but the drift stays. Only
  `terraform apply -replace=<address>` fixes it. A revert issue for this attribute should suggest `-replace`,
  not `-target`.
