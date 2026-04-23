# Pulumi: AWS Nexus AI Baseline

This stack mirrors the Terraform baseline with a minimal Pulumi AWS network scaffold:

- VPC with DNS enabled
- One public subnet and one private subnet
- Internet gateway and public route table
- Application and data security groups
- Deployment templates for multi-region active-active, CDN edge caching, and global latency routing in `templates/`

## Usage

```bash
cd deploy/pulumi/aws-nexus-ai
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pulumi stack init dev
pulumi config set aws:region us-east-1
pulumi up
```

## Templates

The `templates/` directory contains concrete starter templates for:

- `multi_region_active_active.py`
- `cdn_edge_cache.py`
- `global_lb_latency.py`

## Environment Packs

- `Pulumi.dev.yaml`
- `Pulumi.staging.yaml`
- `Pulumi.prod.yaml`

## Verification

- Local: `python scripts/verify_infra_rollout.py`
- CI: `.github/workflows/infra-rollout-verify.yml`

## Notes

This is a repo-local baseline scaffold intended to close the absence of Pulumi modules.
The templates are scaffolds and require stack config (zone IDs, origin domains, endpoint hostnames) before production rollout.
Managed database and Redis provisioning remain follow-on infrastructure work.
