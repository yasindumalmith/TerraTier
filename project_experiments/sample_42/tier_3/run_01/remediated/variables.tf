variable "environment" {
  type    = string
  default = "prod"
}

variable "bucket_suffix" {
  type    = string
  default = "worker-data-42"
}

Note: The storage module now requires an `aws.replica` provider
