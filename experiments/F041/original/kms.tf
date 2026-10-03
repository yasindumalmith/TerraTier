resource "aws_kms_key" "application" {
  description         = "KMS key for application data"
  enable_key_rotation = true

  tags = {
    Purpose = "application-data"
  }
}

resource "aws_kms_key" "logging" {
  description         = "KMS key used only for logging"
  enable_key_rotation = true

  tags = {
    Purpose = "logging"
  }
}

resource "aws_kms_alias" "application" {
  name          = "alias/${var.environment}-application-data"
  target_key_id = aws_kms_key.application.key_id
}

resource "aws_kms_alias" "logging" {
  name          = "alias/${var.environment}-logging"
  target_key_id = aws_kms_key.logging.key_id
}