resource "aws_security_group" "sample_01" {
  name        = "sample-01-open-ssh"
  description = "Research sample with restricted SSH access"

  ingress {
    description = "SSH from the trusted administrative network"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"

    cidr_blocks = [
      "10.0.0.0/24"
    ]
  }

  egress {
    from_port = 0
    to_port   = 0
    protocol  = "-1"

    cidr_blocks = [
      "0.0.0.0/0"
    ]
  }
}
