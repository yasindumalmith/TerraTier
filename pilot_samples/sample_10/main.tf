resource "aws_ecr_repository" "sample_10" {
  name                 = "terratier-research-repository"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = false
  }
}