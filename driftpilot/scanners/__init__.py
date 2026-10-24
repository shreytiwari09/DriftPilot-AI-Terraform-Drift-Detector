"""Build the scanners a config enables. Provider-specific code stays in this package."""

import os

from driftpilot.config import Config
from driftpilot.scanners.base import Scanner


def build_scanners(config: Config) -> list[Scanner]:
    scanners: list[Scanner] = []
    docker_cfg = config.scanners.docker
    if docker_cfg and docker_cfg.enabled:
        import docker

        from driftpilot.scanners.docker import DockerScanner

        scanners.append(
            DockerScanner(docker.from_env(), docker_cfg.managed_label, docker_cfg.ignore_names)
        )
    github_cfg = config.scanners.github
    if github_cfg and github_cfg.enabled:
        from github import Auth, Github

        from driftpilot.scanners.github import GitHubScanner

        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise RuntimeError("GitHub scanner needs GITHUB_TOKEN in the environment")
        scanners.append(
            GitHubScanner(Github(auth=Auth.Token(token)), github_cfg.owner, github_cfg.ignore_names)
        )
    return scanners
