# Stub — scaffolded during architecture planning (2026-08-21), not yet implemented.
# Will hold input variables such as: aws_region, lambda_image_tag, schedule_expression
# (EventBridge cron — timezone still an open decision, see ARCHITECTURE.md § Open items),
# lambda_memory_mb, lambda_timeout_seconds, token_bucket_name. No secret *values* here — those
# stay in SSM Parameter Store (see ssm.tf) and are referenced by name/ARN only.
