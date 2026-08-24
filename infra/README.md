# Infrastructure — Terraform

IaC for the Tech Briefing Pipeline's AWS deployment. Design and decisions live in
[../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) and the full deep-dive in
[../docs/AWS_DEPLOYMENT_PLAN.md](../docs/AWS_DEPLOYMENT_PLAN.md) — read those first, this
folder is the implementation of that plan.

## Status: not yet implemented

The files below are **stubs** scaffolded during architecture planning (2026-08-21) — each has
a header comment describing what it will define. They intentionally contain no real resources
yet: filling them in is implementation work (see the `coding-standards` skill), not planning
work, and doing it before Phase 1 of the migration plan (git init/push, manual OAuth bootstrap)
would be premature.

## Planned layout

| File | Defines |
|---|---|
| `main.tf` | Terraform + provider blocks, remote state backend |
| `variables.tf` | Input variables (region, image tag, schedule expression, etc.) |
| `outputs.tf` | Outputs (Lambda ARN, ECR repo URL, S3 bucket name, etc.) |
| `ecr.tf` | ECR repository for the Lambda container image |
| `lambda.tf` | The Lambda function (container image type) + its execution role |
| `iam.tf` | IAM execution role (CloudWatch Logs, S3 read/write, SSM `GetParameter`) and the GitHub OIDC deploy role (ECR push + `lambda:UpdateFunctionCode` only) |
| `s3.tf` | Small versioned bucket holding `token.json` (and optionally `credentials.json`) |
| `ssm.tf` | SSM Parameter Store entries (`SecureString`) — parameter *definitions* only, values are never committed |
| `eventbridge.tf` | EventBridge Scheduler rule (weekly Monday trigger) invoking the Lambda directly |

## Before running `terraform apply` for the first time

Per [AWS_DEPLOYMENT_PLAN.md §7](../docs/AWS_DEPLOYMENT_PLAN.md#7-migration-phases), Phase 1
(git repo pushed, OAuth `token.json` produced, S3 bucket + SSM params seeded) needs to happen
manually before any of this gets applied. Nothing here should run before that.
