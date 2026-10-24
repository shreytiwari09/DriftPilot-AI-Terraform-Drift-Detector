# GitHub demo: repos, branch protection and team access in a free org.
# Token comes from the GITHUB_TOKEN environment variable, never from a file.
# State is local and gitignored for now; production would use a remote backend with locking.

terraform {
  required_version = ">= 1.5"

  required_providers {
    github = {
      source  = "integrations/github"
      version = "~> 6.13"
    }
  }
}

provider "github" {
  owner = var.owner
}

# Public: branch protection on private repos needs a paid plan.
resource "github_repository" "api" {
  name        = "demo-api"
  description = "DriftPilot demo service (managed by Terraform)"
  visibility  = "public"
  auto_init   = true # creates main, which branch protection needs
  has_issues  = true
  topics      = ["driftpilot", "demo"]
}

resource "github_repository" "web" {
  name        = "demo-web"
  description = "DriftPilot demo frontend (managed by Terraform)"
  visibility  = "public"
  auto_init   = true
  has_issues  = true
  topics      = ["driftpilot", "demo"]
}

resource "github_branch_protection" "api_main" {
  repository_id = github_repository.api.node_id
  pattern       = "main"

  required_pull_request_reviews {
    required_approving_review_count = 2
  }
}

resource "github_team" "developers" {
  name        = "developers"
  description = "Demo team (managed by Terraform)"
  privacy     = "closed"
}

resource "github_team_repository" "developers_api" {
  team_id    = github_team.developers.id
  repository = github_repository.api.name
  permission = "pull"
}
