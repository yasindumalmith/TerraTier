locals {
  table_config = {
    name        = "${var.environment}-${var.table_name}"
    billing     = "PAY_PER_REQUEST"
    hash_key    = "id"
  }

  encryption_keys = {
    application = aws_kms_key.application.arn
    logging     = aws_kms_key.logging.arn
  }
}