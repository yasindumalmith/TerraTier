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
    Statement = [
      {
        Sid = "IAMReadAccess"
        Effect = "Allow"
        Action = [
          "iam:Get*",
          "iam:List*",
          "iam:Describe*"
        ]
        Resource = "*"
      },
      {
        Sid = "IAMWriteAccess"
        Effect = "Allow"
        Action = [
          "iam:CreateUser",
          "iam:DeleteUser",
          "iam:UpdateUser",
          "iam:CreateGroup",
          "iam:DeleteGroup",
          "iam:UpdateGroup",
          "iam:CreateRole",
          "iam:DeleteRole",
          "iam:UpdateRole",
          "iam:CreatePolicy",
          "iam:DeletePolicy",
          "iam:CreatePolicyVersion",
          "iam:DeletePolicyVersion",
          "iam:AttachUserPolicy",
          "iam:DetachUserPolicy",
          "iam:AttachGroupPolicy",
          "iam:DetachGroupPolicy",
          "iam:AttachRolePolicy",
          "iam:DetachRolePolicy",
          "iam:PutUserPolicy",
          "iam:PutGroupPolicy",
          "iam:PutRolePolicy",
          "iam:DeleteUserPolicy",
          "iam:DeleteGroupPolicy",
          "iam:DeleteRolePolicy"
        ]
        Resource = "*"
      }
    ]
  })
}