variable "project_name" {
  description = "Project name used for resource naming"
  type        = string
  default     = "nexus-ai"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "prod"
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "vpc_cidr" {
  description = "VPC CIDR block"
  type        = string
  default     = "10.40.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "Public subnet CIDRs"
  type        = list(string)
  default     = ["10.40.0.0/24", "10.40.1.0/24"]
}

variable "private_subnet_cidrs" {
  description = "Private subnet CIDRs"
  type        = list(string)
  default     = ["10.40.10.0/24", "10.40.11.0/24"]
}

variable "availability_zones" {
  description = "Availability zones matching subnet list order"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

variable "allowed_ingress_cidrs" {
  description = "CIDRs allowed to reach the public app ports"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "tags" {
  description = "Extra resource tags"
  type        = map(string)
  default     = {}
}
