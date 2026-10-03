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

resource "aws_kms_key" "ebs_key" {
  description             = "KMS key for EBS volume encryption"
  deletion_window_in_days = 7
  enable_key_rotation     = true
}

resource "aws_kms_alias" "ebs_key_alias" {
  name          = "alias/ebs-volume-key"
  target_key_id = aws_kms_key.ebs_key.key_id
}

resource "aws_ebs_volume" "sample_03" {
  availability_zone = "us-east-1a"
  size              = 20
  type              = "gp3"
  encrypted         = true
  kms_key_id        = aws_kms_key.ebs_key.arn
  tags              = { Name = "terratier-sample-03" }
}