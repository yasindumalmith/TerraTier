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

resource "aws_kms_key" "sample_04" {
  description = "KMS key for TerraTier sample 04"
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
resource "aws_dynamodb_table" "sample_04" {
  name = "terratier-sample-04"
  billing_mode = "PAY_PER_REQUEST"
  hash_key = "id"
  attribute { 
    name = "id"  
    type = "S" 
    }
  server_side_encryption { 
    enabled = true  
    kms_key_arn = aws_kms_key.sample_04.arn 
    }
  point_in_time_recovery { enabled = false }
}
