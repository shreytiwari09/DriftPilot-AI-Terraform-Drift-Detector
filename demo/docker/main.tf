# Local Docker demo: a small app (web + cache) that DriftPilot watches for drift.
# State is local and gitignored.

terraform {
  required_version = ">= 1.5"

  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 4.6"
    }
  }
}

provider "docker" {}

locals {
  managed_label = { "managed-by" = "terraform", "app" = "driftpilot-demo" }
}

resource "docker_network" "app" {
  name = "driftpilot-demo-net"

  dynamic "labels" {
    for_each = local.managed_label
    content {
      label = labels.key
      value = labels.value
    }
  }
}

resource "docker_volume" "cache_data" {
  name = "driftpilot-demo-cache-data"

  dynamic "labels" {
    for_each = local.managed_label
    content {
      label = labels.key
      value = labels.value
    }
  }
}

resource "docker_image" "nginx" {
  name         = "nginx:alpine"
  keep_locally = true
}

resource "docker_image" "redis" {
  name         = "redis:alpine"
  keep_locally = true
}

resource "docker_container" "web" {
  name   = "driftpilot-demo-web"
  image  = docker_image.nginx.image_id
  memory = 256 # MB
  # Docker defaults swap to 2x memory; without this, every plan wants to "clear" it.
  memory_swap = 512
  restart     = "unless-stopped"

  ports {
    internal = 80
    external = 8080
  }

  networks_advanced {
    name = docker_network.app.id
  }

  dynamic "labels" {
    for_each = local.managed_label
    content {
      label = labels.key
      value = labels.value
    }
  }
}

resource "docker_container" "cache" {
  name        = "driftpilot-demo-cache"
  image       = docker_image.redis.image_id
  memory      = 128 # MB
  memory_swap = 256
  restart     = "unless-stopped"

  volumes {
    volume_name    = docker_volume.cache_data.name
    container_path = "/data"
  }

  networks_advanced {
    name = docker_network.app.id
  }

  dynamic "labels" {
    for_each = local.managed_label
    content {
      label = labels.key
      value = labels.value
    }
  }
}
