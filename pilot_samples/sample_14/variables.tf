variable "aws_region" {
  description = "AWS region used only for Terraform configuration validation and experiments."
  type        = string
  default     = "us-east-1"
}

variable "role_name" {
  type    = string
  default = "terratier-sample-14-role"
}

variable "policy_name" {
  type    = string
  default = "terratier-sample-14-policy"
}
