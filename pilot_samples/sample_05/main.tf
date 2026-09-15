resource "aws_s3_bucket" "sample_05" {
  bucket = "terratier-research-public-bucket-example"
}

resource "aws_s3_bucket_public_access_block" "sample_05" {
  bucket = aws_s3_bucket.sample_05.id

  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

resource "aws_s3_bucket_policy" "sample_05" {
  bucket = aws_s3_bucket.sample_05.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = "*"

        Action = [
          "s3:GetObject"
        ]

        Resource = [
          "${aws_s3_bucket.sample_05.arn}/*"
        ]
      }
    ]
  })
}