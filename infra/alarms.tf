# Backstop alerting that doesn't depend on the pipeline's own code running at all.
#
# src/mailer.py's sendFailureAlert() only fires from inside main.py's try/except --
# it can't catch a crash before that point (e.g. an import-time error, a container
# init failure, an out-of-memory kill). This CloudWatch Alarm watches the Lambda's own
# `Errors` metric instead, which AWS increments regardless of what the code does or
# doesn't get a chance to run, and emails var.my_email via SNS on breach. Added
# 2026-08-28 per docs/TODO.md -- see docs/DECISIONS.md for the reasoning.

resource "aws_sns_topic" "alarms" {
  name = "${var.project_name}-alarms"
}

resource "aws_sns_topic_subscription" "alarms_email" {
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.my_email
  # Note: SNS email subscriptions require manual confirmation -- AWS sends a
  # "Subscription confirmation" email to var.my_email once this is applied; the
  # subscription stays PendingConfirmation (and won't deliver alarms) until that
  # confirmation link is clicked.
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name        = "${var.project_name}-lambda-errors"
  alarm_description = "Fires on any Lambda invocation error, including init-time crashes the pipeline's own alerting can't catch."
  namespace         = "AWS/Lambda"
  metric_name       = "Errors"
  dimensions = {
    FunctionName = aws_lambda_function.this.function_name
  }
  statistic           = "Sum"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  period              = 300 # 5 minutes -- fine-grained enough for a job that runs a few times a week
  evaluation_periods  = 1
  treat_missing_data  = "notBreaching" # no invocation != an error

  alarm_actions = [aws_sns_topic.alarms.arn]
  ok_actions    = [aws_sns_topic.alarms.arn]
}
