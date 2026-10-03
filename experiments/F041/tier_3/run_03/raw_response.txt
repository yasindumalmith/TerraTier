# File: kms.tf
resource "aws_kms_key" "application" {
  description         = "KMS key for application data"
  enable_key_rotation = true

  tags = {
    Purpose = "application-data"
  }
}

resource "aws_kms_key" "logging" {
  description         = "KMS key used only for logging"
  enable_key_rotation = true

  tags = {
    Purpose = "logging"
  }
}

resource "aws_kms_alias" "application" {
  name          = "alias/${var.environment}-application-data"
  target_key_id = aws_kms_key.application.key_id
}

resource "aws_kms_alias" "logging" {
  name          = "alias/${var.environment}-logging"
  target_key_id = aws_kms_key.logging.key_id
}

# File: locals.tf
locals {
  table_config = {
    name        = "${var.environment}-${var.table_name}"
    billing     = "PAY_PER_REQUEST"
    hash_key    = "id"
  }

  encryption_keys = {
    application = aws_kms_key.application.arn
    logging     = aws_kms_key.logging.arn
  }
}

# File: main.tf
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
    enabled     = true
    kms_key_arn = local.encryption_keys.application
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

# File: variables.tf
variable "environment" {
  type    = string
  default = "prod"
}

variable "table_name" {
  type    = string
  default = "orders"
}