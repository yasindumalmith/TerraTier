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

resource "aws_kms_key" "logs" {
  description         = "KMS key for sample 18 logs"
  enable_key_rotation = true
}

resource "aws_cloudwatch_log_group" "sample_18" {
  name              = var.log_group_name
  retention_in_days = 30
  kms_key_id        = aws_kms_key.logs.arn
}

resource "aws_cloudwatch_log_stream" "application" {
  name           = "application"
  log_group_name = aws_cloudwatch_log_group.sample_18.name
}
