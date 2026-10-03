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

resource "aws_kms_key" "dynamodb_key" {
  description             = "KMS key for DynamoDB table sample_11"
  deletion_window_in_days = 7
  enable_key_rotation     = true
}

resource "aws_dynamodb_table" "sample_11" {
  name         = "terratier-sample-11"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"
  attribute {
    name = "id"
    type = "S"
  }
  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.dynamodb_key.arn
  }
  point_in_time_recovery { enabled = true }
}