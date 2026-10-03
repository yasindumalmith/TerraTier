output "kms_key_arn" {
  value = aws_kms_key.storage.arn
}

output "volume_id" {
  value = aws_ebs_volume.sample_15.id
}
