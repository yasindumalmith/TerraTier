terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0, < 7.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

resource "aws_kms_key" "storage" {
  description         = "KMS key available for application storage"
  enable_key_rotation = true
}

resource "aws_kms_alias" "storage" {
  name          = "alias/terratier-sample-15"
  target_key_id = aws_kms_key.storage.key_id
}

resource "aws_ebs_volume" "sample_15" {
  availability_zone = var.availability_zone
  size              = var.volume_size
  type              = "gp3"
  encrypted         = true

  tags = {
    Name = "terratier-sample-15-volume"
  }
}
