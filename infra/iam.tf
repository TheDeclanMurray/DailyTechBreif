# Two distinct identities, kept deliberately separate — neither can do the other's job:
#   1. lambda_execution — assumed by the function itself at runtime. Can read/write this
#      project's own secrets and write its own logs. Cannot touch ECR or itself.
#   2. github_deploy    — assumed by GitHub Actions via OIDC. Can push to ECR and point
#      the Lambda at a new image. Cannot read any secret. If CI is ever compromised, the
#      blast radius stops at "can ship a bad image" — it can't exfiltrate API keys.
#
# (The EventBridge Scheduler's own invoke role lives in eventbridge.tf, next to the
# schedule it serves — it's a third, even narrower identity: invoke this one function.)

# ---------------------------------------------------------------------------
# 1. Lambda execution role
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda_execution" {
  name               = "${var.project_name}-lambda-execution"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

# SSM SecureString params are encrypted under the AWS-managed key by default —
# GetParameter still requires kms:Decrypt on the caller's IAM side even though it's
# the default key, so this is made explicit rather than assumed.
data "aws_kms_alias" "ssm" {
  name = "alias/aws/ssm"
}

data "aws_iam_policy_document" "lambda_execution" {
  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.lambda.arn}:*"]
  }

  statement {
    sid       = "ReadSecrets"
    actions   = ["ssm:GetParameter"]
    resources = [
      aws_ssm_parameter.anthropic_api_key.arn,
      aws_ssm_parameter.smtp_password.arn,
      aws_ssm_parameter.gmail_token.arn,
    ]
  }

  # Narrower than the read scope above on purpose — this is the only parameter the
  # running pipeline ever rewrites (after a Gmail token refresh).
  statement {
    sid       = "WriteRefreshedToken"
    actions   = ["ssm:PutParameter"]
    resources = [aws_ssm_parameter.gmail_token.arn]
  }

  statement {
    sid       = "DecryptSecrets"
    actions   = ["kms:Decrypt"]
    resources = [data.aws_kms_alias.ssm.target_key_arn]
  }
}

resource "aws_iam_role_policy" "lambda_execution" {
  name   = "${var.project_name}-lambda-execution"
  role   = aws_iam_role.lambda_execution.id
  policy = data.aws_iam_policy_document.lambda_execution.json
}

# ---------------------------------------------------------------------------
# 2. GitHub Actions deploy role — assumed via OIDC, not a static access key
# ---------------------------------------------------------------------------

# One-time trust anchor: tells AWS to recognize tokens signed by GitHub's OIDC issuer.
# This alone grants nothing — the actual boundary is the `sub` condition below.
resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]

  # GitHub's OIDC intermediate CA thumbprint. These have rotated before —
  # verify against https://github.blog if `apply` ever fails validating this provider.
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

data "aws_iam_policy_document" "github_deploy_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # This is the line that actually matters: scoped to one repo AND one branch.
    # Loosen this (e.g. drop the branch, or wildcard the repo) and any PR branch —
    # including one from a fork, if this repo is ever public — could assume deploy
    # credentials. Keep it exactly this narrow.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:ref:refs/heads/${var.github_branch}"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name               = "${var.project_name}-github-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_deploy_assume.json
}

data "aws_iam_policy_document" "github_deploy" {
  # AWS requires this specific action be unscoped — it's just the ECR login step,
  # not access to any particular repository's contents.
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "EcrPush"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:PutImage",
      "ecr:BatchGetImage",
    ]
    resources = [aws_ecr_repository.this.arn]
  }

  statement {
    sid       = "DeployLambda"
    actions   = ["lambda:UpdateFunctionCode", "lambda:GetFunction"]
    resources = [aws_lambda_function.this.arn]
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  name   = "${var.project_name}-github-deploy"
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.github_deploy.json
}
