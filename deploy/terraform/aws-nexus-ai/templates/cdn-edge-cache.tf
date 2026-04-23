# Template: CloudFront CDN fronting a regional Nexus AI API origin.
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

resource "aws_cloudfront_origin_access_control" "nexus_api_oac" {
  name                              = "nexus-api-oac"
  description                       = "OAC for Nexus API origin"
  origin_access_control_origin_type = "mediastore"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "nexus_api_cdn" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = ""
  comment             = "Nexus AI API CDN template"

  origin {
    domain_name = var.api_origin_domain
    origin_id   = "nexus-api-origin"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    allowed_methods  = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods   = ["GET", "HEAD", "OPTIONS"]
    target_origin_id = "nexus-api-origin"

    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    forwarded_values {
      query_string = true
      headers      = ["Authorization", "Origin", "Content-Type"]

      cookies {
        forward = "all"
      }
    }

    min_ttl     = 0
    default_ttl = 30
    max_ttl     = 300
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

variable "api_origin_domain" {
  description = "Origin domain for Nexus API (e.g., ALB DNS)"
  type        = string
}

output "cdn_domain_name" {
  value = aws_cloudfront_distribution.nexus_api_cdn.domain_name
}
