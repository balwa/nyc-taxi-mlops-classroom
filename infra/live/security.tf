# S0: security groups and rules. No SSH: shell and UIs go through SSM.
#
# Ingress scope is a decision point (decisions/). This file only consumes var.ingress_cidrs;
# the value lives in your gitignored terraform.tfvars.

resource "aws_security_group" "app" {
  name        = "lab-app"
  description = "App host: Traefik on 80 for ingress_cidrs"
}

resource "aws_security_group" "platform" {
  name        = "lab-platform"
  description = "Platform host: MLflow from app host only"
}

resource "aws_security_group" "llm" {
  name        = "lab-llm"
  description = "LLM host: chat and embeddings from app and platform"
}

resource "aws_security_group" "rds" {
  name        = "lab-rds"
  description = "Postgres from app and platform"
}

# Public entry: Traefik on port 80.
resource "aws_vpc_security_group_ingress_rule" "app_http" {
  for_each          = toset(var.ingress_cidrs)
  security_group_id = aws_security_group.app.id
  cidr_ipv4         = each.value
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  description       = "Traefik"
}

# app -> platform: MLflow
resource "aws_vpc_security_group_ingress_rule" "platform_mlflow" {
  security_group_id            = aws_security_group.platform.id
  referenced_security_group_id = aws_security_group.app.id
  ip_protocol                  = "tcp"
  from_port                    = 5000
  to_port                      = 5000
  description                  = "MLflow from app"
}

# app, platform -> llm: chat (8080) and embeddings (8081)
resource "aws_vpc_security_group_ingress_rule" "llm_from_app" {
  security_group_id            = aws_security_group.llm.id
  referenced_security_group_id = aws_security_group.app.id
  ip_protocol                  = "tcp"
  from_port                    = 8080
  to_port                      = 8081
  description                  = "LLM from app"
}

resource "aws_vpc_security_group_ingress_rule" "llm_from_platform" {
  security_group_id            = aws_security_group.llm.id
  referenced_security_group_id = aws_security_group.platform.id
  ip_protocol                  = "tcp"
  from_port                    = 8080
  to_port                      = 8081
  description                  = "LLM from platform"
}

# app, platform -> rds: Postgres
resource "aws_vpc_security_group_ingress_rule" "rds_from_app" {
  security_group_id            = aws_security_group.rds.id
  referenced_security_group_id = aws_security_group.app.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  description                  = "Postgres from app"
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_platform" {
  security_group_id            = aws_security_group.rds.id
  referenced_security_group_id = aws_security_group.platform.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  description                  = "Postgres from platform"
}

# Hosts need outbound for SSM, GHCR, the GitHub runner and S3. RDS needs none.
resource "aws_vpc_security_group_egress_rule" "hosts" {
  for_each = {
    app      = aws_security_group.app.id
    platform = aws_security_group.platform.id
    llm      = aws_security_group.llm.id
  }
  security_group_id = each.value
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "Outbound"
}
