# Template: Route53 latency-based global load balancing for Nexus AI.
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

resource "aws_route53_health_check" "api_primary" {
  fqdn              = var.primary_endpoint
  port              = 443
  type              = "HTTPS"
  resource_path     = "/health"
  failure_threshold = 3
  request_interval  = 30
}

resource "aws_route53_health_check" "api_secondary" {
  fqdn              = var.secondary_endpoint
  port              = 443
  type              = "HTTPS"
  resource_path     = "/health"
  failure_threshold = 3
  request_interval  = 30
}

resource "aws_route53_record" "api_latency_primary" {
  zone_id = var.public_zone_id
  name    = var.api_hostname
  type    = "CNAME"
  ttl     = 30

  set_identifier = "primary-latency"
  records        = [var.primary_endpoint]
  health_check_id = aws_route53_health_check.api_primary.id

  latency_routing_policy {
    region = var.primary_region
  }
}

resource "aws_route53_record" "api_latency_secondary" {
  zone_id = var.public_zone_id
  name    = var.api_hostname
  type    = "CNAME"
  ttl     = 30

  set_identifier = "secondary-latency"
  records        = [var.secondary_endpoint]
  health_check_id = aws_route53_health_check.api_secondary.id

  latency_routing_policy {
    region = var.secondary_region
  }
}

variable "public_zone_id" {
  type = string
}

variable "api_hostname" {
  type    = string
  default = "api.nexus.local"
}

variable "primary_region" {
  type    = string
  default = "us-east-1"
}

variable "secondary_region" {
  type    = string
  default = "us-west-2"
}

variable "primary_endpoint" {
  description = "Primary API endpoint host (without protocol)"
  type        = string
}

variable "secondary_endpoint" {
  description = "Secondary API endpoint host (without protocol)"
  type        = string
}
