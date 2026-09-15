resource "aws_s3_bucket" "sample_08_logs" {
  bucket = "terratier-cloudtrail-log-example"
}

resource "aws_cloudtrail" "sample_08" {
  name                          = "sample-08-trail"
  s3_bucket_name                = aws_s3_bucket.sample_08_logs.id
  include_global_service_events = true
  is_multi_region_trail         = true

  enable_log_file_validation = false
}