# Outputs listed in contracts/runtime.yaml under terraform_outputs.

output "app_public_ip" {
  value = module.app.public_ip
}

output "app_instance_id" {
  value = module.app.instance_id
}

output "platform_instance_id" {
  value = module.platform.instance_id
}

output "llm_instance_id" {
  value = module.llm.instance_id
}

output "rds_endpoint" {
  value = module.rds.endpoint
}

output "artifact_bucket" {
  value = module.artifact_bucket.name
}

# S3: serving's MLFLOW_TRACKING_URI is built from it (stages/S3.md).
output "platform_private_ip" {
  value = module.platform.private_ip
}
