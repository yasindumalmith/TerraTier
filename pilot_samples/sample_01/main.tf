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
resource "aws_security_group" "sample_01" {
  name = "terratier-sample-01"
  description = "Security group for TerraTier sample 01"
  ingress {
    description = "SSH administration"
    from_port = 22
    to_port = 22
    protocol = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    description = "HTTPS outbound"
    from_port = 443
    to_port = 443
    protocol = "tcp"
    cidr_blocks = ["10.0.0.0/8"]
  }
}
resource "aws_network_interface" "sample_01" {
  subnet_id = var.subnet_id
  security_groups = [aws_security_group.sample_01.id]
}
