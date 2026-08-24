# Architecture — Tech Briefing Pipeline

This is the canonical, always-current architecture summary (per the `coding-architecture`
skill). For the resource-by-resource deep dive — cost estimate, migration phases, full risk
list — see [AWS_DEPLOYMENT_PLAN.md](AWS_DEPLOYMENT_PLAN.md); that document isn't superseded by
this one, it's the detail this one summarizes.

## Repository

GitHub: `https://github.com/TheDeclanMurray/DailyTechBreif.git`

Not yet initialized locally as of 2026-08-21 — no `.git` directory exists in this project yet.
See [ISSUES-ENCOUNTERED.md](ISSUES-ENCOUNTERED.md) for what's blocking the first push.

## Stack

- **Language:** Python 3.12
- **Claude API** (`claude-sonnet-4-6`) — summarizes newsletter emails into a spoken-style
  briefing script, with prompt caching on the email content block
- **Gmail API** (OAuth2, `gmail.readonly`) — source emails
- **piper-tts + ffmpeg** — briefing text → MP3
- **SMTP (587/STARTTLS)** — delivery, with a Gmail App Password

## Containerization

Docker. `Dockerfile` (currently `python:3.12-slim`) + `docker-compose.yml` with two services:
the main pipeline, and a one-off `auth` service that forwards port 8080 for the interactive
OAuth consent redirect (can't run headlessly).

## Hosting & Infrastructure-as-Code

- **Target:** AWS Lambda, **container image** (not zip+layers — piper binary + voice model +
  ffmpeg are large non-pip artifacts, and the Dockerfile already builds this way)
- **Trigger:** Amazon EventBridge Scheduler, weekly cron (Monday 07:00 — timezone still needs an
  explicit decision, EventBridge cron is UTC; see Open Items)
- **Networking:** no VPC attachment needed — outbound-only calls to Gmail API, Anthropic API,
  and Gmail SMTP all work from a non-VPC Lambda by default
- **IaC tool: Terraform** — confirmed by the user 2026-08-21. Chosen over AWS SAM/CDK for being
  cloud-agnostic and mainstream, and because it plugs cleanly into GitHub Actions.
- **Location:** `infra/` at the project root, separate from `src/` — `ecr.tf`, `lambda.tf`,
  `iam.tf`, `eventbridge.tf`, `s3.tf`, `ssm.tf`. Scaffolded as stubs; real resource definitions
  land during implementation (`coding-standards`), not during this planning pass.
- **State/secrets:**
  - OAuth `token.json` persisted to an S3 object (Lambda's filesystem is ephemeral across cold
    starts; refreshed tokens get re-uploaded)
  - App secrets (`ANTHROPIC_API_KEY`, `SMTP_PASSWORD`, etc.) in SSM Parameter Store as
    `SecureString` — free tier, no rotation need here, so Secrets Manager wasn't worth the
    per-secret cost

## CI/CD — GitHub Actions

`.github/workflows/deploy.yml`, triggered on push to `main`:

1. **test job** — `pytest src/tests/unit_tests.py` (the integration suite needs live
   credentials and stays manual-only, never runs in CI)
2. **deploy job** (`needs: test`) — assumes an AWS IAM role via **OIDC federation**
   (`aws-actions/configure-aws-credentials`, `role-to-assume`) — no static AWS access keys
   stored in GitHub at all — then builds the image, pushes to ECR, and runs
   `aws lambda update-function-code`
3. Deploy role ARN + AWS region are stored as GitHub Actions **variables**, not secrets — the
   ARN itself isn't sensitive

Full workflow YAML: [AWS_DEPLOYMENT_PLAN.md §8](AWS_DEPLOYMENT_PLAN.md#8-cicd-pipeline-github-actions).

## Migration status

Not started. [AWS_DEPLOYMENT_PLAN.md §7](AWS_DEPLOYMENT_PLAN.md#7-migration-phases) has the
full phased rollout (bootstrap → Lambda-compatible image → Terraform apply → CI/CD → cutover).
Phase 1 — git init, push to GitHub, S3 bucket, SSM params — is the current blocker.

## Open items

- **Git push credentials** for `https://github.com/TheDeclanMurray/DailyTechBreif.git` — not
  yet resolved this session (no global git identity or `gh` CLI found on this machine); see
  [ISSUES-ENCOUNTERED.md](ISSUES-ENCOUNTERED.md)
- **ffmpeg on Amazon Linux 2023** (the Lambda base image) — not in AL2023's default repos,
  likely needs a static binary; highest-risk unknown, flagged for early testing in Phase 2
- **Piper binary architecture** (x86_64 vs. arm64/Graviton) — must match whichever Lambda
  architecture gets chosen; unconfirmed
- **Lambda memory/timeout sizing** — unmeasured, start generous (1024–2048 MB, 300s) and tune
  from CloudWatch metrics
- **EventBridge cron timezone** — the current Ubuntu cron implicitly used server-local time;
  the EventBridge equivalent needs an explicit UTC-adjusted decision
