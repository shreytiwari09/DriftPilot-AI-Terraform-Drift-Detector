# Per-finding results

✅ severity and action both right · 🟡 one right · ❌ neither (for noise: ✅ = filtered).

| Case | Finding | Expected | raw terraform | rules only | rules + cloud LLM | cloud LLM without rules |
| --- | --- | --- | --- | --- | --- | --- |
| aws-sg-ssh-opened-to-world | `aws_security_group.admin` `ingress[0].cidr_blocks` | critical / revert | ❌ — / — | ✅ critical / revert | ✅ critical / revert | ✅ critical / revert |
| aws-sg-rdp-opened-to-world | `aws_security_group.windows` `ingress[0].cidr_blocks` | critical / revert | ❌ — / — | ✅ critical / revert | ✅ critical / revert | ✅ critical / revert |
| aws-sg-https-opened-to-world | `aws_security_group.web` `ingress[0].cidr_blocks` | high / revert|investigate|codify | ❌ — / — | ❌ — / — | 🟡 critical / revert | 🟡 critical / revert |
| aws-sg-all-ports-opened | `aws_security_group.internal` `ingress[0].cidr_blocks` | critical / revert | ❌ — / — | ✅ critical / revert | ✅ critical / revert | ✅ critical / revert |
| aws-sg-rule-ssh-standalone | `aws_vpc_security_group_ingress_rule.ssh` `cidr_ipv4` | critical / revert | ❌ — / — | ✅ critical / revert | ✅ critical / revert | ✅ critical / revert |
| aws-sg-narrowed | `aws_security_group.app` `ingress[0].cidr_blocks` | medium / codify|investigate | ❌ — / — | ❌ — / — | ✅ medium / investigate | ✅ medium / investigate |
| aws-s3-public-access-block-off | `aws_s3_bucket_public_access_block.data` `block_public_policy` | critical / revert | ❌ — / — | ❌ — / — | ✅ critical / revert | ✅ critical / revert |
| aws-s3-encryption-removed | `aws_s3_bucket_server_side_encryption_configuration.data` `—` | critical / revert|recreate | ❌ — / — | ❌ — / — | ✅ critical / recreate | ✅ critical / recreate |
| aws-s3-versioning-suspended | `aws_s3_bucket_versioning.data` `versioning_configuration[0].status` | high / revert | ❌ — / — | ❌ — / — | ✅ high / revert | ✅ high / revert |
| aws-s3-tags-edited | `aws_s3_bucket.logs` `tags.cost-center` | low / codify|ignore_changes | ❌ — / — | ❌ — / — | ✅ low / codify | ✅ low / codify |
| aws-iam-policy-wildcard | `aws_iam_policy.deploy` `policy` | critical / revert | ❌ — / — | ❌ — / — | ✅ critical / revert | ✅ critical / revert |
| aws-iam-policy-narrowed | `aws_iam_policy.reader` `policy` | medium / codify|investigate | ❌ — / — | ❌ — / — | 🟡 medium / revert | 🟡 medium / revert |
| aws-iam-user-admin-attached | `aws_iam_user_policy_attachment.ci` `policy_arn` | critical / revert | ❌ — / — | ❌ — / — | ✅ critical / revert | ✅ critical / revert |
| aws-instance-type-upsized | `aws_instance.api` `instance_type` | medium / codify|investigate|revert | ❌ — / — | ❌ — / — | ✅ medium / revert | ✅ medium / revert |
| aws-instance-tags-edited | `aws_instance.api` `tags.Name` | low / codify|ignore_changes | ❌ — / — | ❌ — / — | 🟡 low / revert | 🟡 low / revert |
| aws-instance-public-ip | `aws_instance.db_proxy` `associate_public_ip_address` | critical / revert | ❌ — / — | ❌ — / — | ✅ critical / revert | ✅ critical / revert |
| aws-rds-public | `aws_db_instance.main` `publicly_accessible` | critical / revert | ❌ — / — | ❌ — / — | ✅ critical / revert | ✅ critical / revert |
| aws-rds-backup-retention-zero | `aws_db_instance.main` `backup_retention_period` | high / revert | ❌ — / — | ❌ — / — | ✅ high / revert | ✅ high / revert |
| aws-rds-deletion-protection-off | `aws_db_instance.main` `deletion_protection` | high / revert | ❌ — / — | ❌ — / — | ✅ high / revert | ✅ high / revert |
| aws-rds-instance-class | `aws_db_instance.main` `instance_class` | medium / codify|investigate | ❌ — / — | ❌ — / — | 🟡 medium / revert | 🟡 medium / revert |
| aws-cloudtrail-logging-off | `aws_cloudtrail.main` `enable_logging` | critical / revert | ❌ — / — | ❌ — / — | ✅ critical / revert | ✅ critical / revert |
| aws-ebs-volume-deleted | `aws_ebs_volume.data` `—` | high / recreate|investigate | ❌ — / — | ❌ — / — | ✅ high / recreate | ✅ high / recreate |
| aws-asg-max-raised | `aws_autoscaling_group.web` `max_size` | medium / codify|investigate | ❌ — / — | ❌ — / — | 🟡 medium / revert | 🟡 medium / revert |
| aws-lambda-timeout-raised | `aws_lambda_function.worker` `timeout` | medium / codify | ❌ — / — | ❌ — / — | ✅ medium / codify | ✅ medium / codify |
| aws-kms-rotation-off | `aws_kms_key.data` `enable_key_rotation` | high / revert | ❌ — / — | ❌ — / — | 🟡 medium / revert | 🟡 medium / revert |
| docker-web-memory-lowered | `docker_container.web` `memory` | medium / revert|codify|investigate | ❌ — / — | ❌ — / — | ✅ medium / revert | ✅ medium / revert |
| docker-web-memory-lowered | `docker_container.web` `memory_swap` | medium / revert|codify|investigate | ❌ — / — | ❌ — / — | ✅ medium / revert | ✅ medium / revert |
| docker-cache-memory-raised | `docker_container.cache` `memory` | medium / codify|revert | ❌ — / — | ❌ — / — | ✅ medium / codify | ✅ medium / codify |
| docker-restart-no | `docker_container.cache` `restart` | medium / revert|investigate | ❌ — / — | ❌ — / — | ✅ medium / revert | ✅ medium / revert |
| docker-restart-always | `docker_container.web` `restart` | medium / codify | ❌ — / — | ❌ — / — | ✅ medium / codify | ✅ medium / codify |
| docker-web-removed | `docker_container.web` `—` | high / recreate | ❌ — / — | ❌ — / — | ✅ high / recreate | ✅ high / recreate |
| docker-network-removed | `docker_network.app` `—` | high / recreate | ❌ — / — | ❌ — / — | ✅ high / recreate | ✅ high / recreate |
| docker-cpu-shares-lowered | `docker_container.web` `cpu_shares` | medium / codify|revert | ❌ — / — | ❌ — / — | ✅ medium / codify | ✅ medium / codify |
| gh-approvals-2-to-1 | `github_branch_protection.api_main` `required_pull_request_reviews[0].required_approving_review_count` | critical / revert | ❌ — / — | ✅ critical / revert | ✅ critical / revert | ✅ critical / revert |
| gh-approvals-2-to-3-stricter | `github_branch_protection.api_main` `required_pull_request_reviews[0].required_approving_review_count` | medium / codify | ❌ — / — | ❌ — / — | ✅ medium / codify | ✅ medium / codify |
| gh-dismiss-stale-reviews-off | `github_branch_protection.api_main` `required_pull_request_reviews[0].dismiss_stale_reviews` | critical / revert | ❌ — / — | ❌ — / — | 🟡 medium / revert | 🟡 medium / revert |
| gh-enforce-admins-on-stricter | `github_branch_protection.api_main` `enforce_admins` | medium / codify | ❌ — / — | ❌ — / — | ✅ medium / codify | ✅ medium / codify |
| gh-force-push-allowed | `github_branch_protection.api_main` `allows_force_pushes` | critical / revert | ❌ — / — | ❌ — / — | ✅ critical / revert | ✅ critical / revert |
| gh-protection-deletions-allowed | `github_branch_protection.api_main` `allows_deletions` | critical / revert | ❌ — / — | ❌ — / — | 🟡 high / revert | 🟡 high / revert |
| gh-team-pull-to-push | `github_team_repository.developers_api` `permission` | high / revert|investigate | ❌ — / — | ❌ — / — | 🟡 medium / revert | 🟡 medium / revert |
| gh-team-pull-to-maintain | `github_team_repository.developers_api` `permission` | high / revert|investigate | ❌ — / — | ❌ — / — | ✅ high / revert | ✅ high / revert |
| gh-team-admin-to-pull-downgrade | `github_team_repository.developers_api` `permission` | medium / codify|investigate | ❌ — / — | ❌ — / — | 🟡 medium / revert | 🟡 medium / revert |
| gh-repo-api-archived | `github_repository.api` `archived` | high / investigate|revert | ❌ — / — | ❌ — / — | ✅ high / revert | ✅ high / revert |
| gh-repo-made-private | `github_repository.web` `visibility` | high / investigate|revert | ❌ — / — | ❌ — / — | 🟡 medium / revert | 🟡 medium / revert |
| gh-has-wiki-on | `github_repository.web` `has_wiki` | medium / codify|revert | ❌ — / — | ❌ — / — | ✅ medium / revert | ✅ medium / revert |
| gh-delete-branch-on-merge | `github_repository.web` `delete_branch_on_merge` | medium / codify | ❌ — / — | ❌ — / — | 🟡 low / codify | 🟡 low / codify |
| gh-web-description | `github_repository.web` `description` | low / codify | ❌ — / — | ❌ — / — | ✅ low / codify | ✅ low / codify |
| gh-web-homepage | `github_repository.web` `homepage_url` | low / codify | ❌ — / — | ❌ — / — | ✅ low / codify | ✅ low / codify |
| gh-web-topics-removed | `github_repository.web` `topics` | low / codify | ❌ — / — | ❌ — / — | 🟡 low / revert | 🟡 low / revert |
| gh-web-protection-deleted | `github_branch_protection.api_main` `—` | critical / revert|recreate | ❌ — / — | ✅ critical / revert | ✅ critical / revert | ✅ critical / recreate |
| gh-team-privacy-secret | `github_team.developers` `privacy` | medium / codify|revert | ❌ — / — | ❌ — / — | ✅ medium / codify | ✅ medium / codify |
| noise-topics-reordered | `github_repository.api` `topics` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| noise-iam-policy-reformatted | `aws_iam_policy.reader` `policy` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| noise-sg-cidrs-reordered | `aws_security_group.app` `ingress[0].cidr_blocks` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| noise-null-to-false | `aws_s3_bucket.logs` `object_lock_enabled` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| noise-etag-repo | `github_repository.web` `etag` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| noise-network-data-ip | `docker_container.cache` `network_data[0].ip_address` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-gh-s2-approvals-2-to-0 | `github_branch_protection.api_main` `required_pull_request_reviews[0].required_approving_review_count` | critical / revert | ❌ — / — | ✅ critical / revert | ✅ critical / revert | ✅ critical / revert |
| rec-gh-batch-a | `github_branch_protection.api_main` `required_pull_request_reviews[0].required_approving_review_count` | critical / revert | ❌ — / — | ✅ critical / revert | ✅ critical / revert | ✅ critical / revert |
| rec-gh-batch-a | `github_branch_protection.api_main` `required_status_checks` | medium / codify | ❌ — / — | ❌ — / — | ✅ medium / codify | ✅ medium / codify |
| rec-gh-batch-a | `github_repository.api` `description` | low / codify | ❌ — / — | ❌ — / — | ✅ low / codify | ✅ low / codify |
| rec-gh-batch-a | `github_repository.api` `has_issues` | medium / codify|revert | ❌ — / — | ❌ — / — | ✅ medium / revert | ✅ medium / revert |
| rec-gh-batch-a | `github_repository.api` `topics` | low / codify | ❌ — / — | ❌ — / — | ✅ low / codify | ✅ low / codify |
| rec-gh-batch-a | `github_team.developers` `etag` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-gh-batch-a | `github_team_repository.developers_api` `etag` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-gh-batch-a | `github_team_repository.developers_api` `permission` | high / revert|investigate | ❌ — / — | ✅ high / revert | ✅ high / revert | ✅ high / revert |
| rec-gh-batch-b | `github_branch_protection.api_main` `—` | critical / revert|recreate | ❌ — / — | ✅ critical / revert | ✅ critical / revert | ✅ critical / recreate |
| rec-gh-batch-b | `github_repository.web` `archived` | high / investigate|revert | ❌ — / — | ❌ — / — | ✅ high / revert | ✅ high / revert |
| rec-gh-batch-b | `github_repository.web` `vulnerability_alerts` | critical / revert|investigate | ❌ — / — | ❌ — / — | ✅ critical / revert | ✅ critical / revert |
| rec-gh-batch-b | `github_team_repository.developers_api` `etag` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-docker-s10-cache-removed | `docker_container.cache` `—` | high / recreate | ❌ — / — | ❌ — / — | ✅ high / recreate | ✅ high / recreate |
| rec-docker-s11-memory | `docker_container.web` `memory` | medium / codify|revert | ❌ — / — | ❌ — / — | ✅ medium / codify | ✅ medium / codify |
| rec-docker-s11-memory | `docker_container.web` `memory_swap` | medium / codify|revert | ❌ — / — | ❌ — / — | ✅ medium / codify | ✅ medium / codify |
| rec-docker-s12-restart | `docker_container.web` `max_retry_count` | medium / codify | ❌ — / — | ❌ — / — | ✅ medium / codify | ✅ medium / codify |
| rec-docker-s12-restart | `docker_container.web` `restart` | medium / codify | ❌ — / — | ❌ — / — | ✅ medium / codify | ✅ medium / codify |
| rec-docker-cpu-shares | `docker_container.web` `cpu_shares` | medium / codify|revert | ❌ — / — | ❌ — / — | ✅ medium / codify | ✅ medium / codify |
| rec-docker-container-stopped | `docker_container.web` `device_cgroup_rules` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-docker-container-stopped | `docker_container.web` `dns` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-docker-container-stopped | `docker_container.web` `dns_opts` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-docker-container-stopped | `docker_container.web` `dns_search` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-docker-container-stopped | `docker_container.web` `exit_code` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-docker-container-stopped | `docker_container.web` `group_add` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-docker-container-stopped | `docker_container.web` `log_opts` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-docker-container-stopped | `docker_container.web` `must_run` | high / revert|investigate | ❌ — / — | ❌ — / — | 🟡 medium / revert | 🟡 medium / revert |
| rec-docker-container-stopped | `docker_container.web` `network_data[0].gateway` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-docker-container-stopped | `docker_container.web` `network_data[0].ip_address` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-docker-container-stopped | `docker_container.web` `network_data[0].ip_prefix_length` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-docker-container-stopped | `docker_container.web` `network_data[0].mac_address` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-docker-container-stopped | `docker_container.web` `networks_advanced[0].gw_priority` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-docker-container-stopped | `docker_container.web` `ports` | noise | ❌ reported | ❌ reported | ❌ reported | ❌ reported |
| rec-docker-container-stopped | `docker_container.web` `storage_opts` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-docker-container-stopped | `docker_container.web` `sysctls` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-docker-container-stopped | `docker_container.web` `tmpfs` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-first-refresh | `docker_container.cache` `device_cgroup_rules` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-first-refresh | `docker_container.cache` `dns` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-first-refresh | `docker_container.cache` `dns_opts` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-first-refresh | `docker_container.cache` `dns_search` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-first-refresh | `docker_container.cache` `group_add` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-first-refresh | `docker_container.cache` `log_opts` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-first-refresh | `docker_container.cache` `networks_advanced[0].gw_priority` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-first-refresh | `docker_container.cache` `storage_opts` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-first-refresh | `docker_container.cache` `sysctls` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-first-refresh | `docker_container.cache` `tmpfs` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-first-refresh | `docker_container.cache` `volumes[0].read_only` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-first-refresh | `docker_container.web` `device_cgroup_rules` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-first-refresh | `docker_container.web` `dns` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-first-refresh | `docker_container.web` `dns_opts` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-first-refresh | `docker_container.web` `dns_search` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-first-refresh | `docker_container.web` `group_add` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-first-refresh | `docker_container.web` `log_opts` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-first-refresh | `docker_container.web` `networks_advanced[0].gw_priority` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-first-refresh | `docker_container.web` `storage_opts` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-first-refresh | `docker_container.web` `sysctls` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-first-refresh | `docker_container.web` `tmpfs` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-first-refresh | `docker_network.app` `ipam_options` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-first-refresh | `docker_volume.cache_data` `driver_opts` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-restart-mac | `docker_container.web` `device_cgroup_rules` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-restart-mac | `docker_container.web` `dns` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-restart-mac | `docker_container.web` `dns_opts` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-restart-mac | `docker_container.web` `dns_search` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-restart-mac | `docker_container.web` `group_add` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-restart-mac | `docker_container.web` `log_opts` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-restart-mac | `docker_container.web` `network_data[0].mac_address` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-restart-mac | `docker_container.web` `networks_advanced[0].gw_priority` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-restart-mac | `docker_container.web` `storage_opts` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-restart-mac | `docker_container.web` `sysctls` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-docker-restart-mac | `docker_container.web` `tmpfs` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-github-first-refresh | `github_branch_protection.api_main` `force_push_bypassers` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-github-first-refresh | `github_branch_protection.api_main` `required_pull_request_reviews[0].dismissal_restrictions` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-github-first-refresh | `github_branch_protection.api_main` `required_pull_request_reviews[0].pull_request_bypassers` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| rec-noise-github-first-refresh | `github_team.developers` `etag` | noise | ❌ reported | ✅ filtered | ✅ filtered | ✅ filtered |
| unmanaged-github-repo | `repository:demo-handmade` `—` | medium / import | ❌ — / — | ✅ medium / import | ✅ medium / import | ✅ medium / import |
| unmanaged-github-team | `team:on-call` `—` | medium / import | ❌ — / — | ✅ medium / import | ✅ medium / import | ✅ medium / import |
| unmanaged-docker-container | `container:driftpilot-handmade` `—` | medium / import | ❌ — / — | ✅ medium / import | ✅ medium / import | ✅ medium / import |
| unmanaged-docker-volume | `volume:scratch-data` `—` | medium / import | ❌ — / — | ✅ medium / import | ✅ medium / import | ✅ medium / import |
