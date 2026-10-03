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

resource "aws_kms_key" "sample_17" {
  description         = "KMS key for application logs"
  enable_key_rotation = false
}

resource "aws_kms_alias" "logs" {
  name          = "alias/terratier-sample-17-logs"
  target_key_id = aws_kms_key.sample_17.key_id
}

resource "aws_cloudwatch_log_group" "application" {
  name              = var.log_group_name
  retention_in_days = 365
  kms_key_id        = aws_kms_key.sample_17.arn
}
