resource "aws_iam_policy" "sample_02" {
  name        = "sample-02-admin-policy"
  description = "Research sample with excessive permissions"

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Action = [
          "*"
        ]

        Resource = [
          "*"
        ]
      }
    ]
  })
}