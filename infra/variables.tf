# Input variables. No secret *values* here — those live in SSM Parameter Store (ssm.tf)
# and are set out-of-band after `terraform apply`, never committed.

variable "project_name" {
  description = "Short name used to prefix and tag every resource in this stack"
  type        = string
  default     = "daily-tech-brief"
}

variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  # us-east-1: cheapest (tied with us-east-2) US region for Lambda/ECR/CloudWatch/SSM.
  # Latency doesn't matter here (EventBridge-triggered batch job, no one waiting on a
  # request), so cost beat proximity to the user in California. Confirmed 2026-08-24.
  default = "us-east-1"
}

# --- GitHub OIDC trust scoping ---

variable "github_repo" {
  description = "GitHub repo allowed to assume the deploy role, as \"org/repo\""
  type        = string
  default     = "TheDeclanMurray/DailyTechBreif"
}

# GitHub includes these two numeric, immutable IDs in the OIDC token's `sub` claim
# alongside the owner/repo names (format: repo:OWNER@OWNER_ID/REPO@REPO_ID:ref:...) --
# a security feature so a repo rename, transfer, or delete-then-recreate can't silently
# inherit an old trust policy. Discovered 2026-08-26 via CloudTrail after every deploy
# attempt failed AccessDenied against a sub condition that only had the plain names (see
# docs/ISSUES-ENCOUNTERED.md). Re-derive these if the repo is ever transferred:
#   curl https://api.github.com/users/<owner>       -> "id"
#   curl https://api.github.com/repos/<owner>/<repo> -> "id"
variable "github_owner_id" {
  description = "Numeric GitHub owner (account) ID -- part of the immutable OIDC sub claim"
  type        = string
  default     = "111345815"
}

variable "github_repo_id" {
  description = "Numeric GitHub repository ID -- part of the immutable OIDC sub claim"
  type        = string
  default     = "1342264423"
}

variable "github_branch" {
  description = "Branch allowed to assume the deploy role — keep this narrow (see iam.tf)"
  type        = string
  default     = "main"
}

# --- Lambda ---

variable "lambda_image_tag" {
  description = <<-EOT
    Image tag used only on the very first `apply`, before any CI run has ever pushed an
    image. CI's `aws lambda update-function-code` changes the deployed image afterwards;
    `lifecycle.ignore_changes` on the function (see lambda.tf) stops later `apply`s from
    reverting that. Requires an image already pushed to ECR under this tag before the
    first apply — see infra/README.md bootstrap note.
  EOT
  type    = string
  default = "initial"
}

variable "lambda_memory_mb" {
  description = "Starting point per AWS_DEPLOYMENT_PLAN.md — tune down from real CloudWatch metrics"
  type        = number
  default     = 1536
}

variable "lambda_timeout_seconds" {
  type    = number
  default = 600
}

variable "log_retention_days" {
  description = "Must be one of CloudWatch Logs' fixed retention values (0,1,3,5,7,14,30,60,90,...)"
  type        = number
  default     = 14 # closest valid value to the original 10-day intent
}

# --- Secrets (SSM parameter naming only — see ssm.tf for the parameters themselves) ---

variable "ssm_parameter_prefix" {
  type    = string
  default = "/daily-tech-brief"
}

# --- Schedule ---
# EventBridge Scheduler (not classic EventBridge Rules) supports an explicit IANA
# timezone alongside the cron expression, so there's no manual UTC conversion to get
# wrong — set schedule_timezone to wherever "Monday 07:00" is supposed to mean.

variable "schedule_expression" {
  description = "Cron expression, evaluated in schedule_timezone below"
  type        = string
  default     = "cron(0 7 ? * MON-FRI *)"
}

variable "schedule_timezone" {
  description = "IANA timezone the cron above is evaluated in"
  type        = string
  default     = "America/Los_Angeles"
}

# --- Non-secret app config ---
# Passed to the Lambda as plain environment variables. Nothing here is sensitive —
# actual secrets (API keys, SMTP password, the OAuth token blob) live in SSM instead.

variable "newsletter_senders" {
  type    = string
  default = "corey@lastweekinaws.com,dan@tldrnewsletter.com,news@daily.therundown.ai"
}

variable "recipient_emails" {
  type    = string
  default = "dmurray.cobaltix@gmail.com,declan22@gmail.com"
}

variable "developer_email" {
  type    = string
  default = "dmurray.cobaltix@gmail.com"
}

variable "my_email" {
  type    = string
  default = "dmurray.cobaltix@gmail.com"
}

variable "smtp_host" {
  type    = string
  default = "smtp.gmail.com"
}

variable "smtp_port" {
  type    = number
  default = 587
}

variable "smtp_user" {
  type    = string
  default = "dmurray.cobaltix@gmail.com"
}

variable "lookback_days" {
  type    = number
  default = 4
}

variable "tts_voice" {
  type    = string
  default = "en_GB-jenny_dioco-medium"
}

variable "tts_speed" {
  type    = number
  default = 1.4
}
