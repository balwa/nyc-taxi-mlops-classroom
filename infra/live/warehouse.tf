# S1: the Redshift warehouse (contracts/platform.yaml). One ra3.large node by default; clients use the
# Data API with a named database user, so the cluster needs no ingress.

module "redshift" {
  source            = "../modules/redshift"
  subnet_ids        = data.aws_subnets.all.ids
  availability_zone = var.availability_zone
}

output "redshift_cluster_id" {
  value = module.redshift.cluster_id
}

output "redshift_database" {
  value = module.redshift.database
}
