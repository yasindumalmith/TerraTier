variable "aws_region" {
  description = "AWS region used only for Terraform configuration validation and experiments."
  type        = string
  default     = "us-east-1"
}

variable "vpc_id" {
  type    = string
  default = "vpc-0123456789abcdef0"
}

variable "subnet_id" {
  type    = string
  default = "subnet-0123456789abcdef0"
}

variable "private_ip" {
  type    = string
  default = "10.0.3.30"
}

variable "admin_cidr" {
  type    = string
  default = "0.0.0.0/0"
}

variable "internal_cidr" {
  type    = string
  default = "10.0.0.0/8"
}

variable "environment" {
  type    = string
  default = "research"
}
