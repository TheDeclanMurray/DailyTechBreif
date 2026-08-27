# Architecture — Tech Briefing Pipeline

This is the canonical, always-current architecture summary (per the `coding-architecture`
skill). For the resource-by-resource deep dive — cost estimate, migration phases, full risk
list — see [AWS_DEPLOYMENT_PLAN.md](AWS_DEPLOYMENT_PLAN.md); that document isn't superseded by
this one, it's the detail this one summarizes.

## Repository

GitHub: `https://github.com/TheDeclanMurray/DailyTechBreif.git`

Initialized and pushed 2026-08-24 (`main` tracks `origin/main`). As of 2026-08-27, `git log` has
9 commits and the working tree is clean — every `infra/*.tf` file,
`.github/workflows/deploy.yml`, and every fix made while getting the deployed Lambda actually
working is committed and pushed. (The earlier "everything since the initial push is uncommitted"
state noted here previously was resolved same-day, 2026-08-26.)

## Stack

- **Language:** Python 3.12
- **Claude API** (`claude-sonnet-4-6`) — summarizes newsletter emails into a spoken-style
  briefing script, with prompt caching on the email content block
- **Gmail API** (OAuth2, `gmail.readonly`) — source emails
- **piper-tts + ffmpeg** — briefing text → MP3
- **SMTP (587/STARTTLS)** — delivery, with a Gmail App Password

## Containerization

Docker. `Dockerfile` (Lambda-compatible base, `public.ecr.aws/lambda/python:3.12`, Amazon Linux
2023 — switched from `python:3.12-slim` 2026-08-26, see DECISIONS.md) + `docker-compose.yml` with
two services: the main pipeline, and a one-off `auth` service that forwards port 8080 for the
interactive OAuth consent redirect (can't run headlessly). One image serves both: `CMD` points at
the Lambda handler for real deployment, and `docker-compose.yml` overrides `entrypoint`/`command`
to run the pipeline as a plain script for local dev.

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
cutover). As of 2026-08-27: Phase 1 (bootstrap), Phase 2 (Lambda-compatible image/code), Phase 3
(`terraform apply`, 2026-08-25), and Phase 4 (CI/CD — the `deploy` job has succeeded end to end at
least once) are all done. Phase 5 (cutover) hasn't formally started — the pipeline hasn't yet been
confirmed to complete fully end to end on a real deployed invocation (a chain of real bugs, each
only found by testing against the actual Lambda, has kept pushing that confirmation back one step
further each time — see TODO.md), and no EventBridge-triggered run has been checked yet either.

## Open items

- **Full end-to-end confirmation on the deployed Lambda** — the furthest a real
  `aws lambda invoke` has gotten is TTS output; Gmail → Claude → TTS → SMTP with an actual
  delivered email hasn't been confirmed yet. Active blocker on calling Phase 5 done — see
  `docs/TODO.md` for the exact current state.
- **EventBridge-triggered (as opposed to manually invoked) run** — not yet confirmed at all.
- **Lambda memory/timeout sizing** — still unmeasured from a real successful full run; no
  representative CloudWatch data exists yet since no invoke has completed the whole pipeline.

Resolved since this section was last stale (kept here briefly for continuity, remove once this
reads as current for a while): uncommitted local work (all committed 2026-08-26, see Repository
above); ffmpeg on Amazon Linux 2023 (static binary, source switched twice — see
ISSUES-ENCOUNTERED.md); piper binary architecture (x86_64 confirmed working across multiple real
invokes, matches Lambda's default architecture).
