# Infrastructure — Terraform

IaC for the Tech Briefing Pipeline's AWS deployment. Design and decisions live in
[../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) and the full deep-dive in
[../docs/AWS_DEPLOYMENT_PLAN.md](../docs/AWS_DEPLOYMENT_PLAN.md) — read those first, this
folder is the implementation of that plan.

## Status: implemented, not yet applied

The files below were written 2026-08-24 and define real resources — this is no longer a stub
layout. Nothing has been run against AWS yet: Phase 1 of the migration plan (git init/push,
manual OAuth bootstrap, seeding the SSM parameters below with real values) still needs to
happen first. `aws_region` is now confirmed (`us-east-1` — cheapest US region; latency doesn't
matter for a scheduler-triggered batch job). `schedule_timezone` (`America/Los_Angeles`) is
still worth a last look before the first `apply`.

## Layout

| File | Defines |
|---|---|
| `main.tf` | Terraform + provider blocks, remote state backend (currently local state — see the commented-out `backend "s3"` block) |
| `variables.tf` | Input variables (region, image tag, schedule expression, etc.) |
| `outputs.tf` | Outputs (Lambda ARN, ECR repo URL, GitHub deploy role ARN, SSM parameter prefix) |
| `ecr.tf` | ECR repository for the Lambda container image |
| `lambda.tf` | The Lambda function (container image type) + its execution role |
| `iam.tf` | Lambda execution role (CloudWatch Logs, SSM `GetParameter`/`PutParameter`, KMS `Decrypt`) and the GitHub OIDC deploy role (ECR push + `lambda:UpdateFunctionCode` only — cannot read any secret) |
| `ssm.tf` | SSM Parameter Store entries (`SecureString`) — parameter *definitions* only, values are `REPLACE_ME` placeholders until seeded post-`apply`. Also holds the Gmail OAuth `token.json` blob, which replaced the original plan's S3-bucket approach — one parameter is enough since `token.json` already bundles client_id/client_secret/refresh_token |
| `eventbridge.tf` | EventBridge Scheduler rule invoking the Lambda directly, on `var.schedule_expression`/`var.schedule_timezone` from `variables.tf` (currently Mon-Fri 07:00 America/Los_Angeles) |

Note: `docs/AWS_DEPLOYMENT_PLAN.md` still describes the original S3-sync design for `token.json`
and a weekly-Monday-only schedule — both superseded by the above. Worth a pass to bring that
doc in line with what's actually implemented here, separate from this file.

## Before running `terraform apply` for the first time

Per [AWS_DEPLOYMENT_PLAN.md §7](../docs/AWS_DEPLOYMENT_PLAN.md#7-migration-phases), Phase 1
(git repo pushed, OAuth `token.json` produced, S3 bucket + SSM params seeded) needs to happen
manually before any of this gets applied. Nothing here should run before that.
