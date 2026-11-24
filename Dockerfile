# DriftPilot cloud runner image: the same CLI as the GitHub Action, in a container that
# EventBridge/ECS, Cloud Run or a plain VM can run. Nothing here is deployed by this repo.
#
#   docker build -t driftpilot:dev .
#   docker run --rm driftpilot:dev version
#   docker run --rm -v "$PWD/infra:/workspace" driftpilot:dev scan --dir /workspace --no-llm
FROM python:3.12-slim

# Terraform is pinned so every run behaves the same. The download is checked against HashiCorp's
# published SHA256SUMS file (integrity only; the signature is not verified here).
ARG TERRAFORM_VERSION=1.9.8
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git unzip \
    && arch="$(dpkg --print-architecture)" \
    && zip="terraform_${TERRAFORM_VERSION}_linux_${arch}.zip" \
    && base="https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}" \
    && curl -fsSLO "${base}/${zip}" \
    && curl -fsSLO "${base}/terraform_${TERRAFORM_VERSION}_SHA256SUMS" \
    && grep " ${zip}\$" "terraform_${TERRAFORM_VERSION}_SHA256SUMS" | sha256sum -c - \
    && unzip -q "${zip}" terraform -d /usr/local/bin \
    && rm -f "${zip}" "terraform_${TERRAFORM_VERSION}_SHA256SUMS" \
    && apt-get purge -y --auto-remove curl unzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/driftpilot
COPY pyproject.toml README.md ./
COPY driftpilot ./driftpilot
# `aws` = boto3 for the AWS scanner, `db` = psycopg for the Postgres schema check.
RUN pip install --no-cache-dir ".[aws,db]"

# Run as a normal user: the scan only needs to read the Terraform folder and call read-only APIs.
RUN useradd --create-home --uid 10001 driftpilot
USER driftpilot
WORKDIR /workspace

ENTRYPOINT ["driftpilot"]
CMD ["--help"]
