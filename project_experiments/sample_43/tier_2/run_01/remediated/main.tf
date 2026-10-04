data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

resource "aws_kms_key" "rds_kms_key" {
  description             = "KMS key for RDS cluster encryption"
  deletion_window_in_days = 7
  enable_key_rotation     = true
}

resource "aws_iam_role" "backup_role" {
  name = "rds-backup-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "backup.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "backup_policy" {
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForBackup"
  role       = aws_iam_role.backup_role.name
}

resource "aws_backup_vault" "rds_backup_vault" {
  name        = "rds-backup-vault"
  kms_key_arn = aws_kms_key.rds_kms_key.arn
}

resource "aws_backup_plan" "rds_backup_plan" {
  name = "rds-backup-plan"

  rule {
    rule_name         = "rds-backup-rule"
    target_vault_name = aws_backup_vault.rds_backup_vault.name
    schedule          = "cron(0 12 * * ? *)"

    lifecycle {
      delete_after = 35
    }
  }
}

resource "aws_backup_selection" "rds_backup_selection" {
  name         = "rds-backup-selection"
  iam_role_arn = aws_iam_role.backup_role.arn
  plan_id      = aws_backup_plan.rds_backup_plan.id

  resources = [
    aws_rds_cluster.app1-rds-cluster.arn,
    aws_rds_cluster.app2-rds-cluster.arn,
    aws_rds_cluster.app3-rds-cluster.arn,
    aws_rds_cluster.app4-rds-cluster.arn,
    aws_rds_cluster.app5-rds-cluster.arn,
    aws_rds_cluster.app6-rds-cluster.arn,
    aws_rds_cluster.app7-rds-cluster.arn,
    aws_rds_cluster.app8-rds-cluster.arn,
    aws_rds_cluster.app9-rds-cluster.arn,
  ]
}

resource "aws_rds_cluster" "app1-rds-cluster" {
  cluster_identifier        = "app1-rds-cluster"
  allocated_storage         = 10
  backup_retention_period   = 7
  deletion_protection       = true
  iam_database_authentication_enabled = true
  copy_tags_to_snapshot     = true
  storage_encrypted         = true
  kms_key_id                = aws_kms_key.rds_kms_key.arn
  engine                    = "aurora-mysql"
  backtrack_window          = 259200
  enabled_cloudwatch_logs_exports = ["audit", "error", "general", "slowquery"]
  tags = {
    git_commit           = "079fe74f6b96d887c245664fbd8cf676c92f20e5"
    git_file             = "terraform/aws/rds.tf"
    git_last_modified_at = "2021-12-08 23:26:32"
    git_last_modified_by = "tron47@gmail.com"
    git_modifiers        = "tron47"
    git_org              = "matansha"
    git_repo             = "terragoat"
    yor_trace            = "b6f2c2ec-0715-46a0-83d4-502e588826d1"
  }
}

resource "aws_rds_cluster" "app2-rds-cluster" {
  cluster_identifier        = "app2-rds-cluster"
  allocated_storage         = 10
  backup_retention_period   = 7
  deletion_protection       = true
  iam_database_authentication_enabled = true
  copy_tags_to_snapshot     = true
  storage_encrypted         = true
  kms_key_id                = aws_kms_key.rds_kms_key.arn
  engine                    = "aurora-mysql"
  backtrack_window          = 259200
  enabled_cloudwatch_logs_exports = ["audit", "error", "general", "slowquery"]
  tags = {
    git_commit           = "079fe74f6b96d887c245664fbd8cf676c92f20e5"
    git_file             = "terraform/aws/rds.tf"
    git_last_modified_at = "2021-12-08 23:26:32"
    git_last_modified_by = "tron47@gmail.com"
    git_modifiers        = "tron47"
    git_org              = "matansha"
    git_repo             = "terragoat"
    yor_trace            = "d33c9292-952b-4c1f-9973-b6dbad519461"
  }
}

resource "aws_rds_cluster" "app3-rds-cluster" {
  cluster_identifier        = "app3-rds-cluster"
  allocated_storage         = 10
  backup_retention_period   = 15
  deletion_protection       = true
  iam_database_authentication_enabled = true
  copy_tags_to_snapshot     = true
  storage_encrypted         = true
  kms_key_id                = aws_kms_key.rds_kms_key.arn
  engine                    = "aurora-mysql"
  backtrack_window          = 259200
  enabled_cloudwatch_logs_exports = ["audit", "error", "general", "slowquery"]
  tags = {
    git_commit           = "079fe74f6b96d887c245664fbd8cf676c92f20e5"
    git_file             = "terraform/aws/rds.tf"
    git_last_modified_at = "2021-12-08 23:26:32"
    git_last_modified_by = "tron47@gmail.com"
    git_modifiers        = "tron47"
    git_org              = "matansha"
    git_repo             = "terragoat"
    yor_trace            = "2a8584b1-7e9d-4739-8e37-366620c92027"
  }
}

resource "aws_rds_cluster" "app4-rds-cluster" {
  cluster_identifier        = "app4-rds-cluster"
  allocated_storage         = 10
  backup_retention_period   = 15
  deletion_protection       = true
  iam_database_authentication_enabled = true
  copy_tags_to_snapshot     = true
  storage_encrypted         = true
  kms_key_id                = aws_kms_key.rds_kms_key.arn
  engine                    = "aurora-mysql"
  backtrack_window          = 259200
  enabled_cloudwatch_logs_exports = ["audit", "error", "general", "slowquery"]
  tags = {
    git_commit           = "079fe74f6b96d887c245664fbd8cf676c92f20e5"
    git_file             = "terraform/aws/rds.tf"
    git_last_modified_at = "2021-12-08 23:26:32"
    git_last_modified_by = "tron47@gmail.com"
    git_modifiers        = "tron47"
    git_org              = "matansha"
    git_repo             = "terragoat"
    yor_trace            = "284aaeed-fd3f-4b7a-b5f8-61a8457f4d83"
  }
}

resource "aws_rds_cluster" "app5-rds-cluster" {
  cluster_identifier        = "app5-rds-cluster"
  allocated_storage         = 10
  backup_retention_period   = 15
  deletion_protection       = true
  iam_database_authentication_enabled = true
  copy_tags_to_snapshot     = true
  storage_encrypted         = true
  kms_key_id                = aws_kms_key.rds_kms_key.arn
  engine                    = "aurora-mysql"
  backtrack_window          = 259200
  enabled_cloudwatch_logs_exports = ["audit", "error", "general", "slowquery"]
  tags = {
    git_commit           = "079fe74f6b96d887c245664fbd8cf676c92f20e5"
    git_file             = "terraform/aws/rds.tf"
    git_last_modified_at = "2021-12-08 23:26:32"
    git_last_modified_by = "tron47@gmail.com"
    git_modifiers        = "tron47"
    git_org              = "matansha"
    git_repo             = "terragoat"
    yor_trace            = "0b2bea23-5ca5-4bd1-956e-b9ed978daadf"
  }
}

resource "aws_rds_cluster" "app6-rds-cluster" {
  cluster_identifier        = "app6-rds-cluster"
  allocated_storage         = 10
  backup_retention_period   = 15
  deletion_protection       = true
  iam_database_authentication_enabled = true
  copy_tags_to_snapshot     = true
  storage_encrypted         = true
  kms_key_id                = aws_kms_key.rds_kms_key.arn
  engine                    = "aurora-mysql"
  backtrack_window          = 259200
  enabled_cloudwatch_logs_exports = ["audit", "error", "general", "slowquery"]
  tags = {
    git_commit           = "079fe74f6b96d887c245664fbd8cf676c92f20e5"
    git_file             = "terraform/aws/rds.tf"
    git_last_modified_at = "2021-12-08 23:26:32"
    git_last_modified_by = "tron47@gmail.com"
    git_modifiers        = "tron47"
    git_org              = "matansha"
    git_repo             = "terragoat"
    yor_trace            = "fcffb961-d859-4be5-997f-d51b50665ada"
  }
}

resource "aws_rds_cluster" "app7-rds-cluster" {
  cluster_identifier        = "app7-rds-cluster"
  allocated_storage         = 10
  backup_retention_period   = 25
  deletion_protection       = true
  iam_database_authentication_enabled = true
  copy_tags_to_snapshot     = true
  storage_encrypted         = true
  kms_key_id                = aws_kms_key.rds_kms_key.arn
  engine                    = "aurora-mysql"
  backtrack_window          = 259200
  enabled_cloudwatch_logs_exports = ["audit", "error", "general", "slowquery"]
  tags = {
    git_commit           = "079fe74f6b96d887c245664fbd8cf676c92f20e5"
    git_file             = "terraform/aws/rds.tf"
    git_last_modified_at = "2021-12-08 23:26:32"
    git_last_modified_by = "tron47@gmail.com"
    git_modifiers        = "tron47"
    git_org              = "matansha"
    git_repo             = "terragoat"
    yor_trace            = "ebc2ac20-23a3-4518-a7ef-3a102b003ab6"
  }
}

resource "aws_rds_cluster" "app8-rds-cluster" {
  cluster_identifier        = "app8-rds-cluster"
  allocated_storage         = 10
  backup_retention_period   = 25
  deletion_protection       = true
  iam_database_authentication_enabled = true
  copy_tags_to_snapshot     = true
  storage_encrypted         = true
  kms_key_id                = aws_kms_key.rds_kms_key.arn
  engine                    = "aurora-mysql"
  backtrack_window          = 259200
  enabled_cloudwatch_logs_exports = ["audit", "error", "general", "slowquery"]
  tags = {
    git_commit           = "079fe74f6b96d887c245664fbd8cf676c92f20e5"
    git_file             = "terraform/aws/rds.tf"
    git_last_modified_at = "2021-12-08 23:26:32"
    git_last_modified_by = "tron47@gmail.com"
    git_modifiers        = "tron47"
    git_org              = "matansha"
    git_repo             = "terragoat"
    yor_trace            = "af643747-0967-4251-8645-3b54882c2507"
  }
}

resource "aws_rds_cluster" "app9-rds-cluster" {
  cluster_identifier        = "app9-rds-cluster"
  allocated_storage         = 10
  backup_retention_period   = 25
  deletion_protection       = true
  iam_database_authentication_enabled = true
  copy_tags_to_snapshot     = true
  storage_encrypted         = true
  kms_key_id                = aws_kms_key.rds_kms_key.arn
  engine                    = "aurora-mysql"
  backtrack_window          = 259200
  enabled_cloudwatch_logs_exports = ["audit", "error", "general", "slowquery"]
  tags = {
    git_commit           = "079fe74f6b96d887c245664fbd8cf676c92f20e5"
    git_file             = "terraform/aws/rds.tf"
    git_last_modified_at = "2021-12-08 23:26:32"
    git_last_modified_by = "tron47@gmail.com"
    git_modifiers        = "tron47"
    git_org              = "matansha"
    git_repo             = "terragoat"
    yor_trace            = "a0c98536-c751-4743-92f1-a106ce750249"
  }
}
