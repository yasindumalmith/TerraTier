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

resource "aws_kms_key" "sample_10" {
  description             = "KMS key for ECR repository terratier-sample-10"
  deletion_window_in_days = 7
  enable_key_rotation     = true
}

resource "aws_ecr_repository" "sample_10" {
  name                 = "terratier-sample-10"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.sample_10.arn
  }
}