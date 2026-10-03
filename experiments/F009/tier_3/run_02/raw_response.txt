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

variable "ami_id" { 
  type = string  
  default = "ami-0123456789abcdef0" 
  }
variable "subnet_id" { 
  type = string  
  default = "subnet-0123456789abcdef0" 
  }
resource "aws_iam_role" "sample_09" {
  name = "terratier-sample-09-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{ 
      Effect = "Allow"  
      Principal = { Service = "ec2.amazonaws.com" }  
      Action = "sts:AssumeRole" }]
  })
}
resource "aws_iam_instance_profile" "sample_09" {
  name = "terratier-sample-09-profile"
  role = aws_iam_role.sample_09.name
}
resource "aws_instance" "sample_09" {
  ami = var.ami_id
  instance_type = "t3.micro"
  subnet_id = var.subnet_id
  associate_public_ip_address = false
  iam_instance_profile = aws_iam_instance_profile.sample_09.name
  monitoring = true
  ebs_optimized = true
  metadata_options { 
    http_endpoint = "enabled"  
    http_tokens = "required" 
    }
  root_block_device { 
    encrypted = true  
    volume_type = "gp3" 
    }
  tags = { Name = "terratier-sample-09" }
}