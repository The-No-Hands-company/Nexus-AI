module "nexus_ai_network" {
  source = "../../"

  project_name = "nexus-ai"
  environment  = "dev"
  aws_region   = "us-east-1"
}

output "vpc_id" {
  value = module.nexus_ai_network.vpc_id
}
