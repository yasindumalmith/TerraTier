resource "aws_ebs_volume" "sample_03" {
  availability_zone = "us-east-1a"
  size              = 20
  type              = "gp3"

  encrypted = false

  tags = {
    Name = "sample-03-unencrypted-volume"
  }
}