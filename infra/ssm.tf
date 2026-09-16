# SSM Parameter Store — definitions only. Every value below is a placeholder;
# the real secret is set out-of-band after `apply`, e.g.:
#   aws ssm put-parameter --name /daily-tech-brief/ANTHROPIC_API_KEY \
#     --type SecureString --value "sk-ant-..." --overwrite
#
# `lifecycle.ignore_changes = [value]` on every parameter is load-bearing, not
# boilerplate: without it, `apply` would stomp the real secret back to "REPLACE_ME"
# on every subsequent run.
#
# A third parameter, GMAIL_TOKEN_JSON, used to live here holding the Gmail OAuth
# token.json blob, rewritten by the pipeline itself after every token refresh. Removed
# 2026-09-15 when Gmail reading moved to IMAP + App Password — SMTP_PASSWORD now covers
# both reading and sending, and nothing is rewritten at runtime. See docs/DECISIONS.md.

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
  description = "Gmail App Password - used for both SMTP delivery and IMAP newsletter reading (not the account password)"
  type        = "SecureString"
  value       = "REPLACE_ME"

  lifecycle {
    ignore_changes = [value]
  }
}
