# AWS Deployment Plan — Lambda + GitHub Actions CI/CD

The resource-by-resource detail behind [ARCHITECTURE.md](ARCHITECTURE.md)'s canonical summary —
cost estimate, migration phases, full risk list. Not superseded by that file; it's the deep dive
the summary points back to. Snapshot, updated in place as the migration actually progresses
(phase checkboxes, §2's recap, §10's resolved risks) rather than a log — see
[DECISIONS.md](DECISIONS.md)/[ISSUES-ENCOUNTERED.md](ISSUES-ENCOUNTERED.md) for the append-only
history of how it got there.

## 1. Goal

Replace the current on-prem deployment target (Ubuntu server, cron, `docker compose run`) with:
- **AWS Lambda** (container image) running the pipeline on a schedule.
- **GitHub Actions** building/testing/deploying on every push, with no long-lived AWS keys.

This supersedes the "Deployment target" line and the Phase 3 cron item in [CLAUDE.md](../CLAUDE.md).

## 2. Current state (recap)

*Updated 2026-08-31 — see [ARCHITECTURE.md](ARCHITECTURE.md#migration-status) for the canonical
status; this section just keeps the plan's own recap from going stale.*

- Pipeline logic itself is fully implemented and confirmed working locally end-to-end (2026-08-25
  Docker Compose run): `gmail_client.py` → `summarizer.py` → `tts.py` → `mailer.py`, orchestrated
  by `main.py`, with `logger.py` writing to `logs/pipeline.log` and console.
- All of §5 below is now implemented: `src/lambda_handler.py` exists, `Dockerfile` uses the
  Lambda-compatible `public.ecr.aws/lambda/python:3.12` base, `src/config.py` is SSM-aware, and
  `src/logger.py`/`src/tts.py` use `/tmp`-based paths under `IS_LAMBDA`.
- Secrets live in `.env` (git-ignored) and `data/credentials.json` / `data/token.json` (OAuth)
  locally; the SSM equivalents were seeded for real 2026-08-26 (the Terraform-applied
  `REPLACE_ME` placeholders had gone un-noticed until then — see ISSUES-ENCOUNTERED.md) and
  `src/config.py` reads them when `IS_LAMBDA`.
- Local dev still triggered manually via the `run` script → `docker compose run --rm tech-briefing`.
- Git repo: 12 commits, working tree clean, everything (including `infra/`'s real content and
  `.github/workflows/deploy.yml`) committed and pushed.
- `infra/` (§6/§7 below) is applied to real AWS — Lambda, ECR, IAM, SSM, EventBridge Scheduler,
  the CloudWatch alarm backstop — all live, and the `deploy` CI/CD job has succeeded end to end
  multiple times. **All 5 migration phases are now done (2026-08-31)**: a real
  EventBridge-triggered scheduled run completed the entire pipeline (Gmail → Claude → TTS → SMTP
  with a delivered email) — see §7 and `CLAUDE.md`'s Progress section for that date.

## 3. Target architecture

```
GitHub repo (main branch)
  └─▶ GitHub Actions workflow (on push to main)
        ├─▶ pytest tests/unit_tests.py
        ├─▶ assume AWS IAM role via OIDC (no static keys)
        ├─▶ docker build (Lambda-compatible image)
        ├─▶ push to Amazon ECR
        └─▶ aws lambda update-function-code --image-uri ...

Amazon EventBridge Scheduler (cron)
  └─▶ AWS Lambda (container image, from ECR)
        ├─▶ pulls OAuth token.json blob + secrets (Anthropic key, SMTP password) from SSM Parameter Store
        ├─▶ Gmail API ──▶ emails[]
        ├─▶ Claude API ──▶ briefing text
        ├─▶ piper (writes a temp WAV) + ffmpeg (streams MP3 to stdout) ──▶ briefing.mp3 (in-memory bytes, never touches disk — see DECISIONS.md 2026-08-27)
        ├─▶ SMTP (587/STARTTLS) ──▶ email with MP3 attachment
        ├─▶ writes refreshed token.json back to SSM (if rotated)
        └─▶ logs to CloudWatch Logs
```

No VPC needed — Lambda without a VPC attachment has outbound internet access by default, which covers Gmail API, Anthropic API, and Gmail SMTP (port 587).

## 4. Key decisions

| Decision | Choice | Why | Alternative considered |
|---|---|---|---|
| Compute | Lambda, **container image** (not zip+layers) | `piper` binary + voice model + `ffmpeg` are large, non-pip artifacts — container image (up to 10GB) is the natural fit; Dockerfile already builds this way | Fargate scheduled task — more natural for long-running/large containers, but this job is a few-minute batch job well within Lambda's 15-min cap, so Lambda is cheaper and simpler |
| OAuth token persistence | SSM Parameter Store, `SecureString` (same mechanism as app secrets, below) | Lambda's filesystem is ephemeral across cold starts; token must survive and be re-written after refresh. `token.json` already bundles client_id/client_secret/refresh_token and fits comfortably under SSM's 4KB standard-parameter limit, so one parameter covers it — no separate bucket to provision, version, or grant access to | S3 object — originally planned, dropped since it's one more service/IAM surface for no benefit over just using SSM like everything else; Secrets Manager — works too, slightly more expensive per-secret |
| App secrets (API keys, SMTP password) | SSM Parameter Store, `SecureString` | Free (vs. Secrets Manager's per-secret charge), sufficient for this scale, native `boto3` support | Secrets Manager — better if rotation is ever needed; not needed here |
| Scheduling | EventBridge Scheduler rule → invoke Lambda directly | Native, no server, exact cron control, explicit IANA timezone support | Keep cron on an EC2 box calling Lambda — pointless extra moving part |
| IaC | Terraform | Cloud-agnostic, mainstream, plugs cleanly into GitHub Actions | AWS SAM/CDK — more Lambda-idiomatic, reasonable second choice if preferred |
| GitHub → AWS auth | OIDC federation (`aws-actions/configure-aws-credentials` with `role-to-assume`) | No long-lived AWS access keys stored in GitHub secrets | Static IAM user access keys — simpler to set up but a standing credential risk |

## 5. Code changes required

New:
- **`src/lambda_handler.py`** — new entry point with `def handler(event, context)` wrapping the existing `main()` pipeline logic.
- **`infra/`** (Terraform) — `ecr.tf`, `lambda.tf`, `iam.tf`, `eventbridge.tf`, `ssm.tf` (values *not* committed, only parameter definitions — this includes the OAuth `token.json` blob, not just app secrets).
- **`.github/workflows/deploy.yml`** — CI/CD pipeline (see §7).

Modified:
- **`Dockerfile`** — needs a Lambda-compatible variant:
  - Base image must become `public.ecr.aws/lambda/python:3.12` (Amazon Linux 2023) instead of `python:3.12-slim` (Debian). This changes the package manager (`dnf`/`yum`, not `apt-get`).
  - **Verify `ffmpeg` availability** — not in AL2023 default repos; likely need a static build (e.g. BtbN's static Linux binaries) instead of a package install.
  - **Verify the `piper` release binary's architecture** matches the Lambda architecture you pick (x86_64 vs arm64/Graviton) — confirm before switching, don't assume.
  - `CMD` becomes `[ "src.lambda_handler.handler" ]` per the Lambda Runtime Interface.
- **`src/config.py`** — needs to source secrets from SSM (`boto3.client('ssm').get_parameter`) and detect Lambda vs local (`AWS_LAMBDA_FUNCTION_NAME` env var present) rather than only reading `.env`. Keep local `.env` path working for dev.
- **`src/gmail_client.py` / `src/auth.py`** — add SSM sync: fetch the `GMAIL_TOKEN_JSON` parameter to `/tmp` on cold start; after any token refresh, `ssm:PutParameter` the updated blob back. `auth.py`'s interactive OAuth flow itself **cannot run in Lambda** (needs a browser redirect) — it stays a local/manual one-time bootstrap step (see §7, Phase 1).
- **`src/logger.py`** — file handler should write to `/tmp/pipeline.log` in Lambda (not `data/`), and console output already flows to CloudWatch automatically. `readLogTail()` used by `sendFailureAlert` keeps working as-is since it only needs the current invocation's own log file.
- **`CLAUDE.md`** — once this lands, update the "Deployment target" line, the Phase 3 checklist, and the Component Connections diagram to reflect Lambda + EventBridge instead of cron + Ubuntu.

No changes needed to `summarizer.py`, `tts.py`'s core logic, or `mailer.py` — their logic is transport-agnostic.

## 6. AWS resources (new)

| Resource | Purpose |
|---|---|
| ECR repository | Stores the Lambda container image |
| Lambda function (container image type) | Runs the pipeline |
| IAM execution role | CloudWatch Logs write, SSM `GetParameter` (all secrets) + `PutParameter` (token refresh only) + KMS `Decrypt` |
| IAM OIDC deploy role (trust = `token.actions.githubusercontent.com`, scoped to this repo) | Used by GitHub Actions — least privilege: ECR push + `lambda:UpdateFunctionCode` only |
| SSM Parameter Store entries (`SecureString`) | `ANTHROPIC_API_KEY`, `SMTP_PASSWORD`, `GMAIL_TOKEN_JSON`, others from `.env.example` |
| EventBridge Scheduler rule | Cron + explicit IANA timezone (EventBridge Scheduler, unlike classic EventBridge Rules, takes a timezone directly — no manual UTC conversion) |
| CloudWatch Log group | Retention policy (e.g. 30 days) for Lambda logs |

## 7. Migration phases

- [x] **Phase 1 — Bootstrap (manual, one-time)**
  - [x] Initialize git repo, push to GitHub (2026-08-24)
  - [x] Run `auth.py` locally as today to produce a valid `token.json`
  - [x] Create SSM parameters for all `.env` secrets, including `GMAIL_TOKEN_JSON` seeded with the `token.json` contents above (seeded for real 2026-08-26 — see §2)
- [x] **Phase 2 — Lambda-compatible image**
  - [x] Fork `Dockerfile` to Lambda base image, resolve `ffmpeg`/`piper` availability on Amazon Linux (ffmpeg's source needed a second fix 2026-08-27 after the first static-binary host started blocking CI traffic — see ISSUES-ENCOUNTERED.md)
  - [x] Write `src/lambda_handler.py`
  - [x] Update `config.py` to read from SSM in Lambda, `.env` locally
  - [x] Update `gmail_client.py`/`auth.py` for SSM token sync
  - [x] Test the image locally before ever pushing to AWS (via real `docker build` + booting through the actual Lambda `CMD`, not the standalone RIE tool)
- [x] **Phase 3 — Infra (Terraform)**
  - [x] `ecr.tf`, `iam.tf`, `lambda.tf`, `ssm.tf`, `eventbridge.tf` written (2026-08-24) — see `infra/README.md`
  - [x] `terraform apply` run manually (2026-08-25) — all resources live, verified via AWS CLI
- [x] **Phase 4 — CI/CD (GitHub Actions)**
  - [x] OIDC trust relationship + deploy role written in Terraform (`infra/iam.tf`, applied 2026-08-25; `sub` condition corrected 2026-08-26 to match GitHub's real token — see DECISIONS.md)
  - [x] `.github/workflows/deploy.yml` written (§8) and pushed to GitHub (2026-08-26)
  - [x] Store the deploy role ARN, AWS region, ECR repo, and Lambda function name as GitHub repo **variables** (all four ended up needing to move from secrets to variables 2026-08-26 — see ISSUES-ENCOUNTERED.md); `deploy` job has succeeded end to end at least once
- [x] **Phase 5 — Cutover**
  - [x] Confirm a real `aws lambda invoke` completes the entire pipeline (Gmail → Claude → TTS → SMTP, actual email delivered) — confirmed via a real EventBridge-triggered run (see next item) 2026-08-31
  - [x] Confirm an actual EventBridge-triggered run behaves the same as a manual invoke — the scheduled Mon–Fri 07:00 run fired for real 2026-08-31 and completed the whole pipeline; see `CLAUDE.md`'s Progress section for that date (a duplicate-email bug was also found and fixed the same day — Lambda timeout was too tight, see DECISIONS.md/ISSUES-ENCOUNTERED.md)
  - [x] Update `CLAUDE.md` Progress/Known Issues sections to match once both are confirmed — done 2026-08-31

## 8. CI/CD pipeline (GitHub Actions)

`.github/workflows/deploy.yml`, triggered on push to `main`:

```yaml
name: Deploy
on:
  push:
    branches: [main]

permissions:
  id-token: write   # required for OIDC
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -r requirements.txt pytest
      - run: python -m pytest src/tests/unit_tests.py -v

  deploy:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ vars.AWS_DEPLOY_ROLE_ARN }}
          aws-region: ${{ vars.AWS_REGION }}
      - uses: aws-actions/amazon-ecr-login@v2
        id: ecr
      - name: Build and push image
        run: |
          IMAGE="${{ steps.ecr.outputs.registry }}/tech-briefing:${{ github.sha }}"
          docker build -t "$IMAGE" .
          docker push "$IMAGE"
          echo "IMAGE=$IMAGE" >> "$GITHUB_ENV"
      - name: Update Lambda
        run: |
          aws lambda update-function-code \
            --function-name tech-briefing \
            --image-uri "$IMAGE"
          aws lambda wait function-updated \
            --function-name tech-briefing
```

`src/tests/integration_tests.py` stays out of CI (as today) since it needs live credentials — run manually only.

*Note: the sample above is illustrative and predates the real file. The actual
[`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) uses repo variables
(`vars.ECR_REPOSITORY`, `vars.LAMBDA_FUNCTION_NAME`) instead of the hardcoded `tech-briefing`
name shown here, matching `var.project_name`'s real default of `daily-tech-brief` in
`infra/variables.tf`.*

## 9. Cost estimate (rough)

Few-minute invocation on a weekday schedule: Lambda compute + ECR storage + SSM + CloudWatch Logs all sit comfortably in the AWS free tier or amount to **well under $1–2/month**. The dominant ongoing spend stays the Anthropic API usage, unchanged by this migration.

## 10. Open questions / risks

- **Timeout/memory sizing**: timeout is resolved — a real full run measured at ~300–311s wall
  clock, right at the old 300s timeout, which caused a duplicate-email bug (see
  ISSUES-ENCOUNTERED.md's 2026-08-31 entry); raised to 600s for headroom (see DECISIONS.md).
  Memory is still unmeasured against a representative real run — `infra/variables.tf` defaults to
  1536MB as a starting point, not a measured value — tracked in `docs/TODO.md`. Lambda hard cap is
  15 min regardless.
- ~~**`ffmpeg` on Amazon Linux 2023**: needs a static-binary approach, not `apt-get`.~~ Resolved:
  static binary baked into the Dockerfile. The source needed to change twice —
  johnvansickle.com first (2026-08-26), then BtbN/FFmpeg-Builds after johnvansickle started
  blocking/challenging GitHub Actions runner IPs specifically (2026-08-27) — see
  ISSUES-ENCOUNTERED.md.
- ~~**Piper binary architecture**: confirm the release binary matches whichever Lambda
  architecture you choose.~~ Resolved: x86_64 confirmed working across multiple real
  `aws lambda invoke` calls, matches Lambda's default architecture (`infra/lambda.tf` leaves
  `architectures` unset).
- ~~**Ephemeral storage**: default `/tmp` is 512MB; check actual `briefing.mp3` + intermediate WAV
  size and bump `EphemeralStorage` config if needed.~~ Superseded 2026-08-27: the MP3 is no
  longer written anywhere, including `/tmp` — only the intermediate WAV (piper's output, a few
  MB at most) touches `/tmp` now, comfortably inside the 512MB default. See DECISIONS.md.
- ~~**Timezone for the trigger**: EventBridge Scheduler cron expressions are UTC — pick and document the intended timezone explicitly (the current Ubuntu cron implicitly used server-local time).~~ Resolved: EventBridge *Scheduler* (as opposed to classic EventBridge Rules) takes an explicit IANA timezone alongside the cron expression, so no manual UTC conversion is needed — set to `America/Los_Angeles` in `infra/variables.tf`'s `schedule_timezone`, with `schedule_expression` set to weekdays at 07:00 (`cron(0 7 ? * MON-FRI *)`).
