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

    # Explicitly no retries. EventBridge Scheduler's default is 185 attempts, which is
    # actively harmful for this workload: the pipeline is not idempotent past the point
    # where sendBriefing() succeeds, and main.py emails a failure alert on every failed
    # run. A retried run therefore means either a duplicate briefing or a burst of alert
    # emails. This is the real root cause of the 2026-08-31 duplicate-briefing bug --
    # a run hit the 300s timeout after delivering, and the default retry policy ran the
    # whole pipeline again. Raising lambda_timeout_seconds to 600 made that specific
    # trigger unlikely but left the retry behaviour in place; this removes it.
    #
    # Failures are still surfaced, just not by retrying: src/lambda_handler.py raises on
    # a non-zero exit, which increments the Lambda Errors metric and trips the
    # CloudWatch alarm in alarms.tf. One missed briefing is recoverable -- the next run
    # picks the emails up again, since markEmailsAsProcessed() only labels after a
    # successful delivery.
    retry_policy {
      maximum_retry_attempts = 0
    }
  }
}
