resource "aws_kms_key" "sample_09" {
  description = "Research key with rotation disabled"

  enable_key_rotation = false

  tags = {
    Name = "sample-09-key"
  }
}