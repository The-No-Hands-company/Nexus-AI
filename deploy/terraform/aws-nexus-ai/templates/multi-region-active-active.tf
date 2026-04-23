# Template: active-active multi-region deployment bootstrap for Nexus AI.
# This file is a deployment template and is not auto-applied by the base module.

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

provider "aws" {
  alias  = "primary"
  region = var.primary_region
}

provider "aws" {
  alias  = "secondary"
  region = var.secondary_region
}

module "network_primary" {
  source = "../"
  providers = {
    aws = aws.primary
  }

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.primary_region
  vpc_cidr     = var.primary_vpc_cidr
}

module "network_secondary" {
  source = "../"
  providers = {
    aws = aws.secondary
  }

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.secondary_region
  vpc_cidr     = var.secondary_vpc_cidr
}

# Weighted DNS split template for active-active traffic policy.
resource "aws_route53_record" "api_primary_weighted" {
  zone_id = var.public_zone_id
  name    = var.api_hostname
  type    = "CNAME"
  ttl     = 30

  set_identifier = "primary"
  records        = [var.primary_api_endpoint]

  weighted_routing_policy {
    weight = var.primary_weight
  }
}

resource "aws_route53_record" "api_secondary_weighted" {
  zone_id = var.public_zone_id
  name    = var.api_hostname
  type    = "CNAME"
  ttl     = 30

  set_identifier = "secondary"
  records        = [var.secondary_api_endpoint]

  weighted_routing_policy {
    weight = var.secondary_weight
  }
}

variable "project_name" {
  type    = string
  default = "nexus-ai"
}

variable "environment" {
  type    = string
  default = "prod"
}

variable "primary_region" {
  type    = string
  default = "us-east-1"
}

variable "secondary_region" {
  type    = string
  default = "us-west-2"
}

variable "primary_vpc_cidr" {
  type    = string
  default = "10.60.0.0/16"
}

variable "secondary_vpc_cidr" {
  type    = string
  default = "10.61.0.0/16"
}

variable "public_zone_id" {
  type = string
}

variable "api_hostname" {
  type    = string
  default = "api.nexus.local"
}

variable "primary_api_endpoint" {
  type = string
}

variable "secondary_api_endpoint" {
  type = string
}

variable "primary_weight" {
  type    = number
  default = 50
}

variable "secondary_weight" {
  type    = number
  default = 50
}
