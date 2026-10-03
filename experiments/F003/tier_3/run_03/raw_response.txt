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

resource "aws_kms_key" "sample_03" {
  description             = "CMK for encrypting EBS volume sample_03"
  enable_key_rotation     = true
  deletion_window_in_days = 7
}

resource "aws_ebs_volume" "sample_03" {
  availability_zone = "us-east-1a"
  size              = 20
  type              = "gp3"
  encrypted         = true
  kms_key_id        = aws_kms_key.sample_03.arn
  tags = { Name = "terratier-sample-03" }
}