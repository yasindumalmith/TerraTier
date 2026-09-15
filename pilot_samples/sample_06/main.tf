resource "aws_s3_bucket" "sample_06" {
  bucket = "terratier-research-unencrypted-example"

  tags = {
    Environment = "research"
  }
}