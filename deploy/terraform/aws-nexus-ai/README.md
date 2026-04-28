# Terraform: AWS Nexus AI Baseline

This module provides a baseline AWS network foundation for Nexus AI deployments:

- VPC with DNS enabled
- Public and private subnets across two AZs
- Internet gateway and public route table
- Application security group for 80/443 ingress
- Data security group for PostgreSQL and Redis from the app tier
- Deployment templates for multi-region active-active, CDN edge caching, and global latency routing in `templates/`

## Usage

```hcl
module "nexus_ai_network" {
  source = "./deploy/terraform/aws-nexus-ai"

  project_name = "nexus-ai"
  environment  = "prod"
  aws_region   = "us-east-1"
}
```

## Templates

The `templates/` directory contains concrete starter templates for:

- `multi-region-active-active.tf`
- `cdn-edge-cache.tf`
- `global-lb-latency-routing.tf`

## Environment Packs

- `env/dev.tfvars`
- `env/staging.tfvars`
- `env/prod.tfvars`

Use with:

```bash
terraform plan -var-file=env/dev.tfvars
terraform plan -var-file=env/staging.tfvars
terraform plan -var-file=env/prod.tfvars
```

## Verification

- Local: `python scripts/verify_infra_rollout.py --run-terraform-validate`
- CI: `.github/workflows/infra-rollout-verify.yml`

## Notes

This is a baseline module intended to move the infrastructure backlog from absent to implementation-backed.
The templates are intentionally provider-specific scaffolds and require environment values (DNS zone IDs, origin hostnames, region endpoints) before production apply.
Managed database/redis provisioning still remains follow-on infrastructure work.
