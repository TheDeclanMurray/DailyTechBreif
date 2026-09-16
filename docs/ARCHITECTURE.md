# Architecture — Tech Briefing Pipeline

This is the canonical, always-current architecture summary (per the `coding-architecture`
skill). For the resource-by-resource deep dive — cost estimate, migration phases, full risk
list — see [AWS_DEPLOYMENT_PLAN.md](AWS_DEPLOYMENT_PLAN.md); that document isn't superseded by
this one, it's the detail this one summarizes.

## Repository

GitHub: `https://github.com/TheDeclanMurray/DailyTechBreif.git`

Initialized and pushed 2026-08-24 (`main` tracks `origin/main`). As of 2026-08-31, `git log` has
12 commits and the working tree is clean.

## Stack

- **Language:** Python 3.12
- **Claude API** (`claude-sonnet-4-6`) — summarizes newsletter emails into a spoken-style
  briefing script, with prompt caching on the email content block
- **Gmail over IMAP** (`imaplib`, stdlib) authenticated with a Gmail App Password — source
  emails. Replaced the Gmail API + OAuth2 on 2026-09-15: `gmail.modify` is a Google *restricted*
  scope, which forced the consent screen to either sit in "Testing" mode (refresh token expires
  every 7 days — it silently killed a week of briefings) or pass a paid verification audit. Gmail's
  `X-GM-RAW`/`X-GM-LABELS`/`X-GM-MSGID` IMAP extensions preserve the original search-and-label
  behaviour. See DECISIONS.md.
- **piper-tts + ffmpeg** — briefing text → MP3
- **SMTP (587/STARTTLS)** — delivery, with a Gmail App Password

## Containerization

Docker. `Dockerfile` (Lambda-compatible base, `public.ecr.aws/lambda/python:3.12`, Amazon Linux
2023 — switched from `python:3.12-slim` 2026-08-26, see DECISIONS.md) + `docker-compose.yml` with
two services: the main pipeline, and a `test` service built from `Dockerfile.test` (plain
`python:3.12-slim`) for the unit suite. `CMD` points at the Lambda handler for real deployment, and
`docker-compose.yml` overrides `entrypoint`/`command` to run the pipeline as a plain script for
local dev. The one-off `auth` service that used to forward port 8080 for the OAuth consent
redirect was removed 2026-09-15 along with the OAuth flow itself.

## Hosting & Infrastructure-as-Code

- **Target:** AWS Lambda, **container image** (not zip+layers — piper binary + voice model +
  ffmpeg are large non-pip artifacts, and the Dockerfile already builds this way). Timeout `600s`
  (raised from `300s` 2026-08-31 — see DECISIONS.md), memory `1536MB` (still unmeasured against
  real usage, see TODO.md).
- **Trigger:** Amazon EventBridge Scheduler, weekday cron `cron(0 7 ? * MON-FRI *)` evaluated in
  the `America/Los_Angeles` IANA timezone (EventBridge Scheduler, unlike classic EventBridge
  Rules, takes an explicit timezone so there's no manual UTC conversion — see DECISIONS.md).
- **Networking:** no VPC attachment needed — outbound-only calls to Gmail IMAP (993), the
  Anthropic API, and Gmail SMTP (587) all work from a non-VPC Lambda by default. This is
  load-bearing for IMAP specifically: a non-VPC Lambda has unrestricted AWS-managed egress,
  whereas the Cobaltix office network resets TLS on 993, making local testing impossible (see
  ISSUES-ENCOUNTERED.md).
- **IaC tool: Terraform** — confirmed by the user 2026-08-21. Chosen over AWS SAM/CDK for being
  cloud-agnostic and mainstream, and because it plugs cleanly into GitHub Actions.
- **Location:** `infra/` at the project root, separate from `src/` — `main.tf`, `variables.tf`,
  `outputs.tf`, `ecr.tf`, `lambda.tf`, `iam.tf`, `eventbridge.tf`, `ssm.tf`, `alarms.tf` (the
  CloudWatch `Errors` alarm → SNS → email backstop, added 2026-08-28).
- **State/secrets:**
  - No runtime-mutable credential at all since 2026-09-15. The `GMAIL_TOKEN_JSON` SSM parameter
    (which the pipeline rewrote after every OAuth refresh) and the execution role's
    `ssm:PutParameter` permission were both removed with the move to IMAP — the App Password in
    `SMTP_PASSWORD` now covers reading and sending, and nothing changes at runtime, so the
    execution role is strictly read-only against Parameter Store.
  - App secrets (`ANTHROPIC_API_KEY`, `SMTP_PASSWORD`) in SSM Parameter Store as
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
3. Deploy role ARN, AWS region, ECR repository, and Lambda function name are all stored as
   GitHub Actions **variables**, not secrets — none of the four are sensitive (all had to be
   moved from secrets to variables 2026-08-26 after `deploy.yml`'s `vars.*` reads came up empty,
   see ISSUES-ENCOUNTERED.md)

Full workflow YAML: [AWS_DEPLOYMENT_PLAN.md §8](AWS_DEPLOYMENT_PLAN.md#8-cicd-pipeline-github-actions).

## Migration status

Ran out of phase order originally (Phase 3 landed before Phase 2), which is what caused the
deployed Lambda to crash on every invocation for two days before anyone noticed — see
[ISSUES-ENCOUNTERED.md](ISSUES-ENCOUNTERED.md). [AWS_DEPLOYMENT_PLAN.md §7](AWS_DEPLOYMENT_PLAN.md#7-migration-phases)
has the full phased rollout (bootstrap → Lambda-compatible image → Terraform apply → CI/CD →
cutover). **All 5 phases are now done as of 2026-08-31**: Phase 1 (bootstrap), Phase 2
(Lambda-compatible image/code), Phase 3 (`terraform apply`, 2026-08-25), Phase 4 (CI/CD), and
Phase 5 (cutover) — a real EventBridge-triggered scheduled run completed the full pipeline
(Gmail → Claude → TTS → SMTP) end to end and delivered the briefing, closing out the chain of
real-invoke bugs tracked here since 2026-08-26 (see CLAUDE.md's Progress section for the full
list and ISSUES-ENCOUNTERED.md for each one's diagnosis).

## Open items

- **Lambda memory sizing** — `lambda_memory_mb` (`1536`) is still the pre-launch starting
  estimate, not measured against real usage now that full runs are completing — see
  `docs/TODO.md`.

Resolved since this section was last stale (kept here briefly for continuity, remove once this
reads as current for a while): full end-to-end pipeline confirmation on the deployed Lambda, and
on a real EventBridge-triggered (not just manually invoked) run — both confirmed 2026-08-31; the
Lambda timeout that caused a duplicate-email bug that same day was also found and fixed (300s →
600s, see DECISIONS.md).
