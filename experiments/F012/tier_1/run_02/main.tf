terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

variable "subnet_id" { 
  type = string  
  default = "subnet-0123456789abcdef0" 
  }
resource "aws_security_group" "sample_12" {
  name = "terratier-sample-12"
  description = "Security group for TerraTier sample 12"
  ingress { 
    from_port = 443  
    to_port = 443  
    protocol = "tcp"  
    cidr_blocks = ["10.0.0.0/8"]
    description = "Allow HTTPS from internal network"
    }
  egress { 
    from_port = 443  
    to_port = 443  
    protocol = "tcp"  
    cidr_blocks = ["10.0.0.0/8"]
    description = "Allow HTTPS to internal network"
    }
}
resource "aws_network_interface" "sample_12" {
  subnet_id = var.subnet_id
  security_groups = [aws_security_group.sample_12.id]
}