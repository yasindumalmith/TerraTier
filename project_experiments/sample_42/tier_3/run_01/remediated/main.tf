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

module "storage" {
  source = "./modules/storage"

  environment   = var.environment
  bucket_suffix = var.bucket_suffix
}

resource "aws_iam_role" "worker" {
  name = "${var.environment}-worker-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = {
          Service = "lambda.amazonaws.com"
        }

        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_policy" "worker" {
  name = "${var.environment}-worker-policy"

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid    = "ObjectAccess"
        Effect = "Allow"

        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject"
        ]

        Resource = local.resource_scope.object_path
      },

      {
        Sid    = "BucketAccess"
        Effect = "Allow"

        Action = [
          "s3:ListBucket"
        ]

        Resource = local.resource_scope.bucket_path
      },

      {
        Sid    = "EncryptionAccess"
        Effect = "Allow"

        Action = [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:GenerateDataKey"
        ]

        Resource = local.resource_scope.encryption_target
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "worker" {
  role       = aws_iam_role.worker.name
  policy_arn = aws_iam_policy.worker.arn
}
