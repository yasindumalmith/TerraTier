terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0, < 7.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

locals {
  administrative_cidrs = [var.admin_cidr]
  common_tags = {
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

resource "aws_security_group" "sample_25" {
  name        = "terratier-sample-25"
  description = "Administrative access for a private workload"
  vpc_id      = var.vpc_id

  ingress {
    description = "SSH administration"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = local.administrative_cidrs
  }

  egress {
    description = "HTTPS to internal services"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.internal_cidr]
  }

  tags = merge(local.common_tags, {
    Name = "terratier-sample-25"
  })
}

resource "aws_network_interface" "workload" {
  subnet_id       = var.subnet_id
  security_groups = [aws_security_group.sample_25.id]
  private_ips     = [var.private_ip]

  tags = local.common_tags
}
