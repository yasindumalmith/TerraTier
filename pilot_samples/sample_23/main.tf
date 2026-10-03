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

resource "aws_kms_key" "database" {
  description         = "Customer-managed key available for sample 23"
  enable_key_rotation = true
}

resource "aws_kms_alias" "database" {
  name          = "alias/terratier-sample-23-db"
  target_key_id = aws_kms_key.database.key_id
}

resource "aws_dynamodb_table" "sample_23" {
  name         = var.table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }
}
