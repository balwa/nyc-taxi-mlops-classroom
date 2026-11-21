# S0: root module wiring. Modules are given in ../modules; inputs are in variables.tf.

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "all" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# The three hosts share one AZ (variables.tf) so traffic between them stays in-AZ.
data "aws_subnet" "host" {
  vpc_id            = data.aws_vpc.default.id
  availability_zone = var.availability_zone
  default_for_az    = true
}

module "platform" {
  source             = "../modules/host"
  role               = "platform"
  instance_type      = var.platform_instance_type
  subnet_id          = data.aws_subnet.host.id
  security_group_ids = [aws_security_group.platform.id]
}

module "app" {
  source             = "../modules/host"
  role               = "app"
  instance_type      = var.app_instance_type
  subnet_id          = data.aws_subnet.host.id
  security_group_ids = [aws_security_group.app.id]
}

module "llm" {
  source             = "../modules/host"
  role               = "llm"
  instance_type      = var.llm_instance_type
  subnet_id          = data.aws_subnet.host.id
  security_group_ids = [aws_security_group.llm.id]
}

module "rds" {
  source             = "../modules/rds"
  instance_class     = var.rds_instance_class
  subnet_ids         = data.aws_subnets.all.ids
  security_group_ids = [aws_security_group.rds.id]
}

module "artifact_bucket" {
  source = "../modules/bucket"
  name   = "lab-artifacts"
}

module "wiki_secret" {
  source      = "../modules/secret"
  name        = "lab/wiki"
  description = "Wiki URL and token for the MCP server (S7). Value is put out of band."
}
