# VPC / Private Network Rollout (Starter)

## Objectives

- Move from baseline templates to environment-specific rollout plans
- Define private endpoint and peering/transit requirements
- Produce deployment gates for dev/staging/prod

## Existing Technical Baseline

- Terraform baseline module: `deploy/terraform/aws-nexus-ai/`
- Terraform infra templates: `deploy/terraform/aws-nexus-ai/templates/`
- Pulumi baseline module: `deploy/pulumi/aws-nexus-ai/`
- Pulumi infra templates: `deploy/pulumi/aws-nexus-ai/templates/`

## Initial Deliverables

1. Environment-specific CIDR and route plans
2. PrivateLink/private endpoint matrix (DB, cache, storage)
3. Security group and NACL policy review checklist
4. Cutover runbook with rollback steps

## Exit Criteria to Promote From Partial

- Staging deployment completed with private connectivity
- Peering/transit and endpoint policies verified
- Production change advisory approved
