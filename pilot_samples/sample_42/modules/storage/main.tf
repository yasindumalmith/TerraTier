resource "aws_kms_key" "data" {
  description         = "Encryption key for worker payload data"
  enable_key_rotation = true
}

resource "aws_s3_bucket" "data" {
  bucket = "${var.environment}-${var.bucket_suffix}"
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.data.arn
      sse_algorithm     = "aws:kms"
    }
  }
}
