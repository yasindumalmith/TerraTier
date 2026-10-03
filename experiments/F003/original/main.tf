terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

resource "aws_ebs_volume" "sample_03" {
  availability_zone = "us-east-1a"
  size = 20
  type = "gp3"
  encrypted = true
  tags = { Name = "terratier-sample-03" }
}
