# S2: the SageMaker notebook (infra/modules/notebook), in the same subnet as the hosts so it can reach
# MLflow on the platform host (port 5000, runtime.yaml). It clones github_repo (public) and writes the
# settings below to ~/SageMaker/.lab.env, which notebooks/explore.ipynb reads.

module "notebook" {
  source    = "../modules/notebook"
  subnet_id = data.aws_subnet.host.id
  repo_url  = "https://github.com/${var.github_repo}"
  env = {
    MLFLOW_TRACKING_URI = "http://${module.platform.private_ip}:5000"
    REDSHIFT_CLUSTER_ID = module.redshift.cluster_id
    REDSHIFT_DATABASE   = module.redshift.database
    REDSHIFT_DB_USER    = module.redshift.admin_user
  }
}

# The notebook may reach MLflow on the platform host, like the app host does.
resource "aws_vpc_security_group_ingress_rule" "platform_mlflow_from_notebook" {
  security_group_id            = aws_security_group.platform.id
  referenced_security_group_id = module.notebook.security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 5000
  to_port                      = 5000
  description                  = "MLflow from the notebook"

  lifecycle {
    precondition {
      condition     = var.github_repo != null
      error_message = "Set github_repo (owner/name) in terraform.tfvars: the notebook clones your public repo."
    }
  }
}

output "notebook_name" {
  value = module.notebook.name
}
