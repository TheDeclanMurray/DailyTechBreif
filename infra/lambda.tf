# The Lambda function itself — container image type, pointing at the ECR repo in ecr.tf.
#
# Bootstrap gotcha: on the very first `apply`, this resource requires an image to
# already exist at image_uri below — Lambda validates the image on creation. Push one
# real (or placeholder) build to ECR first:
#   aws ecr get-login-password | docker login --username AWS --password-stdin <repo-url>
#   docker build -t <repo-url>:initial .
#   docker push <repo-url>:initial
# before running `terraform apply` for the first time. See infra/README.md.

resource "aws_cloudwatch_log_group" "lambda" {
  # Matches the log group name Lambda would auto-create anyway — declaring it
  # explicitly is what lets us set a retention policy (default is "never expire").
  name              = "/aws/lambda/${var.project_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "this" {
  function_name = var.project_name
  role          = aws_iam_role.lambda_execution.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.this.repository_url}:${var.lambda_image_tag}"

  memory_size = var.lambda_memory_mb
  timeout     = var.lambda_timeout_seconds

  # Non-secret config only. Secrets (API keys, SMTP password, the OAuth token blob)
  # are read from SSM at runtime instead — see ssm.tf and src/config.py.
  environment {
    variables = {
      SSM_PARAMETER_PREFIX = var.ssm_parameter_prefix
      NEWSLETTER_SENDERS   = var.newsletter_senders
      RECIPIENT_EMAILS     = var.recipient_emails
      DEVELOPER_EMAIL      = var.developer_email
      MY_EMAIL             = var.my_email
      SMTP_HOST            = var.smtp_host
      SMTP_PORT            = tostring(var.smtp_port)
      SMTP_USER            = var.smtp_user
      LOOKBACK_DAYS        = tostring(var.lookback_days)
      TTS_VOICE            = var.tts_voice
      TTS_SPEED            = tostring(var.tts_speed)
    }
  }

  # Explicit dependency so the log group Terraform manages is created before the
  # function is, rather than racing Lambda's own auto-created one.
  depends_on = [aws_cloudwatch_log_group.lambda]

  lifecycle {
    # CI deploys via `aws lambda update-function-code`, not `terraform apply`, on
    # every push after the first. Without this, the next `apply` would revert the
    # function back to whatever lambda_image_tag resolves to — fighting CI.
    ignore_changes = [image_uri]
  }
}
