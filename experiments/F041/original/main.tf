terraform {
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

resource "aws_dynamodb_table" "sample_27" {
  name         = local.table_config.name
  billing_mode = local.table_config.billing
  hash_key     = local.table_config.hash_key

  attribute {
    name = "id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true

    # Intentionally missing customer-managed KMS key.
    # Expected Checkov finding: CKV_AWS_119
  }

  tags = {
    Environment = var.environment
    Application = "order-service"
  }
}

resource "aws_cloudwatch_log_group" "application" {
  name              = "/${var.environment}/orders"
  retention_in_days = 365
  kms_key_id        = local.encryption_keys.logging
}