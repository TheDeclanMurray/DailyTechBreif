# EventBridge Scheduler (the newer, dedicated scheduling service — distinct from
# classic EventBridge Rules) invokes the Lambda directly, no intermediary. Chosen
# specifically because it supports schedule_expression_timezone natively — classic
# EventBridge Rules cron expressions are UTC-only and would need a manual conversion.

# A third, narrow identity: only allowed to invoke this one function, nothing else.
data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler_invoke" {
  name               = "${var.project_name}-scheduler-invoke"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

data "aws_iam_policy_document" "scheduler_invoke" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.this.arn]
  }
}

resource "aws_iam_role_policy" "scheduler_invoke" {
  name   = "${var.project_name}-scheduler-invoke"
  role   = aws_iam_role.scheduler_invoke.id
  policy = data.aws_iam_policy_document.scheduler_invoke.json
}

resource "aws_scheduler_schedule" "weekly_briefing" {
  name       = "${var.project_name}-weekly"
  group_name = "default"

  flexible_time_window {
    mode = "OFF" # fire at exactly the scheduled time — no jitter needed for this
  }

  schedule_expression          = var.schedule_expression
  schedule_expression_timezone = var.schedule_timezone

  target {
    arn      = aws_lambda_function.this.arn
    role_arn = aws_iam_role.scheduler_invoke.arn
  }
}
