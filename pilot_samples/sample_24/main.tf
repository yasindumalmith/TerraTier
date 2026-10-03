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

resource "aws_security_group" "sample_24" {
  name   = "terratier-sample-24"
  vpc_id = var.vpc_id

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.application_cidr]
  }

  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.egress_cidr]
  }

  tags = {
    Name = "terratier-sample-24"
  }
}

resource "aws_network_interface" "application" {
  subnet_id       = var.subnet_id
  private_ips     = ["10.0.2.25"]
  security_groups = [aws_security_group.sample_24.id]
}
