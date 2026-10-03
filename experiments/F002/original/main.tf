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

resource "aws_iam_policy" "sample_02" {
  name = "terratier-sample-02"
  description = "Intentionally over-permissive IAM policy for TerraTier"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid = "FullIAMAccess"
      Effect = "Allow"
      Action = "iam:*"
      Resource = "*"
    }]
  })
}
