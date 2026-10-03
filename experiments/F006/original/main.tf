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

resource "aws_kms_key" "sample_06" {
  description = "KMS key for TerraTier sample 06"
  enable_key_rotation = true
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid = "EnableRootPermissions"
      Effect = "Allow"
      Principal = { AWS = "arn:aws:iam::123456789012:root" }
      Action = "kms:*"
      Resource = "*"
    }]
  })
}
resource "aws_cloudwatch_log_group" "sample_06" {
  name = "/terratier/sample-06"
  retention_in_days = 30
  kms_key_id = aws_kms_key.sample_06.arn
}
