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

locals {
  administrative_actions = ["iam:*"]
  policy_name             = "${var.project_name}-administration"
}

data "aws_iam_policy_document" "assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "application" {
  name               = "${var.project_name}-role"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
}

resource "aws_iam_policy" "sample_26" {
  name = local.policy_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "AdministrativeIamAccess"
        Effect   = "Allow"
        Action   = local.administrative_actions
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "application" {
  role       = aws_iam_role.application.name
  policy_arn = aws_iam_policy.sample_26.arn
}
