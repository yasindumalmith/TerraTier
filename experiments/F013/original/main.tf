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

resource "aws_security_group" "sample_13" {
  name        = "terratier-sample-13"
  description = "Medium-complexity administration security group"
  vpc_id      = var.vpc_id

  ingress {
    description = "Administrative SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.admin_cidr]
  }

  egress {
    description = "Outbound access"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/8"]
  }

  tags = {
    Name        = "terratier-sample-13"
    Environment = var.environment
  }
}

resource "aws_network_interface" "app" {
  subnet_id       = var.subnet_id
  private_ips     = [var.private_ip]
  security_groups = [aws_security_group.sample_13.id]

  tags = {
    Name = "sample-13-app-eni"
  }
}
