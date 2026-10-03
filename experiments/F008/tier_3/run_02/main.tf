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

resource "aws_kms_key" "sample_08" {
  description = "KMS key for TerraTier sample 08"
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
resource "aws_ecr_repository" "sample_08" {
  name = "terratier-sample-08"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
  encryption_configuration { 
    encryption_type = "KMS"  
    kms_key = aws_kms_key.sample_08.arn 
    }
}