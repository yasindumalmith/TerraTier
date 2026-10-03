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

resource "aws_kms_key" "ebs_sample_03" {
  description             = "CMK for EBS volume terratier-sample-03"
  deletion_window_in_days = 7
  enable_key_rotation     = true
}

resource "aws_ebs_volume" "sample_03" {
  availability_zone = "us-east-1a"
  size              = 20
  type              = "gp3"
  encrypted         = true
  kms_key_id        = aws_kms_key.ebs_sample_03.arn
  tags              = { Name = "terratier-sample-03" }
}