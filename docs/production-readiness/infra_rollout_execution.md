# Infrastructure Rollout Execution Pack

This pack operationalizes infrastructure rollout across environments using concrete config packs and verification tooling.

## Environment Config Packs

### Terraform

- `deploy/terraform/aws-nexus-ai/env/dev.tfvars`
- `deploy/terraform/aws-nexus-ai/env/staging.tfvars`
- `deploy/terraform/aws-nexus-ai/env/prod.tfvars`

### Pulumi

- `deploy/pulumi/aws-nexus-ai/Pulumi.dev.yaml`
- `deploy/pulumi/aws-nexus-ai/Pulumi.staging.yaml`
- `deploy/pulumi/aws-nexus-ai/Pulumi.prod.yaml`

## Verification Tooling

- Local verification script: `scripts/verify_infra_rollout.py`
- CI verification workflow: `.github/workflows/infra-rollout-verify.yml`
- IaC packaging/validation workflow: `.github/workflows/iac-modules-release.yml`

## Execution Criteria

1. Config packs exist for dev/staging/prod in both Terraform and Pulumi.
2. Verification script passes in CI with terraform validate enabled.
3. Release-readiness workflow produces packaged module artifacts.

## Remaining External Dependencies

- Cloud account credentials and remote state backends.
- DNS zone ownership and production cutover approvals.
- Region-level data replication and failover rehearsal windows.
