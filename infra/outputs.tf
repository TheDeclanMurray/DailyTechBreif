output "lambda_function_arn" {
  value = aws_lambda_function.this.arn
}

output "ecr_repository_url" {
  description = "Push new images here — consumed by the GitHub Actions deploy job"
  value       = aws_ecr_repository.this.repository_url
}

output "github_deploy_role_arn" {
  description = "Set this as the AWS_DEPLOY_ROLE_ARN GitHub Actions repo *variable* (not a secret — the ARN itself isn't sensitive)"
  value       = aws_iam_role.github_deploy.arn
}

output "ssm_parameter_prefix" {
  value = var.ssm_parameter_prefix
}
