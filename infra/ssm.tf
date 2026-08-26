# SSM Parameter Store — definitions only. Every value below is a placeholder;
# the real secret is set out-of-band after `apply`, e.g.:
#   aws ssm put-parameter --name /daily-tech-brief/ANTHROPIC_API_KEY \
#     --type SecureString --value "sk-ant-..." --overwrite
#
# `lifecycle.ignore_changes = [value]` on every parameter is load-bearing, not
# boilerplate: without it, `apply` would stomp the real secret back to "REPLACE_ME"
# on every subsequent run. For gmail_token specifically it matters even more — the
# running pipeline itself rewrites this value after every OAuth token refresh, and
# Terraform must never fight that.

resource "aws_ssm_parameter" "anthropic_api_key" {
  name        = "${var.ssm_parameter_prefix}/ANTHROPIC_API_KEY"
  description = "Anthropic Claude API key"
  type        = "SecureString"
  value       = "REPLACE_ME"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "smtp_password" {
  name        = "${var.ssm_parameter_prefix}/SMTP_PASSWORD"
  description = "Gmail App Password used for SMTP delivery (not the account password)"
  type        = "SecureString"
  value       = "REPLACE_ME"

  lifecycle {
    ignore_changes = [value]
  }
}

# Replaces the S3-bucket approach from the original plan. token.json (produced by
# src/auth.py, run locally) already bundles client_id/client_secret/refresh_token —
# so this one parameter is the only place the Gmail OAuth credential needs to live.
# Comfortably inside SSM's 4KB standard-parameter limit.
resource "aws_ssm_parameter" "gmail_token" {
  name        = "${var.ssm_parameter_prefix}/GMAIL_TOKEN_JSON"
  description = "Gmail OAuth2 token.json blob — seeded from a local src/auth.py run, rewritten by the pipeline itself after each token refresh"
  type        = "SecureString"
  value       = "REPLACE_ME"

  lifecycle {
    ignore_changes = [value]
  }
}
