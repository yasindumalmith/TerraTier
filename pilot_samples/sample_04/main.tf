resource "aws_db_instance" "sample_04" {
  identifier = "sample-04-database"

  engine         = "mysql"
  engine_version = "8.0"

  instance_class        = "db.t3.micro"
  allocated_storage     = 20
  username              = "adminuser"
  password              = "ResearchOnlyPassword123!"
  skip_final_snapshot   = true
  publicly_accessible   = false
  storage_encrypted     = false
}