output "bucket_arn" {
  value = aws_s3_bucket.data.arn
}

output "kms_key_arn" {
  value = aws_kms_key.data.arn
}
