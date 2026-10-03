variable "aws_region" {
  description = "AWS region used only for Terraform configuration validation and experiments."
  type        = string
  default     = "us-east-1"
}

variable "ami_id" {
  type    = string
  default = "ami-0123456789abcdef0"
}

variable "instance_type" {
  type    = string
  default = "t3.micro"
}

variable "subnet_id" {
  type    = string
  default = "subnet-0123456789abcdef0"
}
