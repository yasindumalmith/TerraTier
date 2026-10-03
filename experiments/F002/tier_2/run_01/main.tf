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
  name        = "terratier-sample-02"
  description = "Intentionally over-permissive IAM policy for TerraTier"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "LimitedIAMAccess"
      Effect = "Allow"
      Action = [
        "iam:GetUser",
        "iam:GetRole",
        "iam:GetPolicy",
        "iam:ListUsers",
        "iam:ListRoles",
        "iam:ListPolicies",
        "iam:ListAttachedRolePolicies",
        "iam:ListAttachedUserPolicies",
        "iam:ListRolePolicies",
        "iam:ListUserPolicies",
        "iam:GetRolePolicy",
        "iam:GetUserPolicy",
        "iam:GetPolicyVersion",
        "iam:ListPolicyVersions"
      ]
      Resource = "*"
    }]
  })
}