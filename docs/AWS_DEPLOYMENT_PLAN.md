# AWS Deployment Plan — Lambda + GitHub Actions CI/CD

## 1. Goal

Replace the current on-prem deployment target (Ubuntu server, cron, `docker compose run`) with:
- **AWS Lambda** (container image) running the pipeline on a schedule.
- **GitHub Actions** building/testing/deploying on every push, with no long-lived AWS keys.

This supersedes the "Deployment target" line and the Phase 3 cron item in [CLAUDE.md](../CLAUDE.md).

## 2. Current state (recap)

- Pipeline is fully implemented: `gmail_client.py` → `summarizer.py` → `tts.py` → `mailer.py`, orchestrated by `main.py`, with `logger.py` writing to `logs/pipeline.log` and console.
- Runs as a Docker container built from a Debian-slim (`python:3.12-slim`) `Dockerfile` with `piper` + `ffmpeg` + a baked-in voice model.
- Secrets live in `.env` (git-ignored) and `data/credentials.json` / `data/token.json` (OAuth).
- Triggered manually/by cron via the `run` script → `docker compose run --rm tech-briefing`.
- **The project is not yet a git repo** (confirmed: no `.git` present). This must happen before GitHub Actions can exist.

## 3. Target architecture

```
GitHub repo (main branch)
  └─▶ GitHub Actions workflow (on push to main)
        ├─▶ pytest tests/unit_tests.py
        ├─▶ assume AWS IAM role via OIDC (no static keys)
        ├─▶ docker build (Lambda-compatible image)
        ├─▶ push to Amazon ECR
        └─▶ aws lambda update-function-code --image-uri ...

Amazon EventBridge Scheduler (cron, Mon 07:00)
  └─▶ AWS Lambda (container image, from ECR)
        ├─▶ pulls OAuth token.json from S3 (or Secrets Manager)
        ├─▶ pulls secrets (Anthropic key, SMTP password) from SSM Parameter Store
        ├─▶ Gmail API ──▶ emails[]
        ├─▶ Claude API ──▶ briefing text
        ├─▶ piper + ffmpeg (in /tmp) ──▶ briefing.mp3
        ├─▶ SMTP (587/STARTTLS) ──▶ email with MP3 attachment
        ├─▶ writes refreshed token.json back to S3 (if rotated)
        └─▶ logs to CloudWatch Logs
```

No VPC needed — Lambda without a VPC attachment has outbound internet access by default, which covers Gmail API, Anthropic API, and Gmail SMTP (port 587).

## 4. Key decisions

| Decision | Choice | Why | Alternative considered |
|---|---|---|---|
| Compute | Lambda, **container image** (not zip+layers) | `piper` binary + voice model + `ffmpeg` are large, non-pip artifacts — container image (up to 10GB) is the natural fit; Dockerfile already builds this way | Fargate scheduled task — more natural for long-running/large containers, but this job is a few-minute batch job well within Lambda's 15-min cap, so Lambda is cheaper and simpler |
| OAuth token persistence | S3 object (`token.json`) | Lambda's filesystem is ephemeral across cold starts; token must survive and be re-uploaded after refresh | Secrets Manager — works too, slightly more expensive per-secret, marginally more code for read/write-back; S3 is simpler for a single blob |
| App secrets (API keys, SMTP password) | SSM Parameter Store, `SecureString` | Free (vs. Secrets Manager's per-secret charge), sufficient for this scale, native `boto3` support | Secrets Manager — better if rotation is ever needed; not needed here |
| Scheduling | EventBridge Scheduler rule → invoke Lambda directly | Native, no server, exact cron control (weekly Monday) | Keep cron on an EC2 box calling Lambda — pointless extra moving part |
| IaC | Terraform | Cloud-agnostic, mainstream, plugs cleanly into GitHub Actions | AWS SAM/CDK — more Lambda-idiomatic, reasonable second choice if preferred |
| GitHub → AWS auth | OIDC federation (`aws-actions/configure-aws-credentials` with `role-to-assume`) | No long-lived AWS access keys stored in GitHub secrets | Static IAM user access keys — simpler to set up but a standing credential risk |

## 5. Code changes required

New:
- **`src/lambda_handler.py`** — new entry point with `def handler(event, context)` wrapping the existing `main()` pipeline logic.
- **`infra/`** (Terraform) — `ecr.tf`, `lambda.tf`, `iam.tf`, `eventbridge.tf`, `s3.tf`, `ssm.tf` (values *not* committed, only parameter definitions).
- **`.github/workflows/deploy.yml`** — CI/CD pipeline (see §7).

Modified:
- **`Dockerfile`** — needs a Lambda-compatible variant:
  - Base image must become `public.ecr.aws/lambda/python:3.12` (Amazon Linux 2023) instead of `python:3.12-slim` (Debian). This changes the package manager (`dnf`/`yum`, not `apt-get`).
  - **Verify `ffmpeg` availability** — not in AL2023 default repos; likely need a static build (e.g. BtbN's static Linux binaries) instead of a package install.
  - **Verify the `piper` release binary's architecture** matches the Lambda architecture you pick (x86_64 vs arm64/Graviton) — confirm before switching, don't assume.
  - `CMD` becomes `[ "src.lambda_handler.handler" ]` per the Lambda Runtime Interface.
- **`src/config.py`** — needs to source secrets from SSM (`boto3.client('ssm').get_parameter`) and detect Lambda vs local (`AWS_LAMBDA_FUNCTION_NAME` env var present) rather than only reading `.env`. Keep local `.env` path working for dev.
- **`src/gmail_client.py` / `src/auth.py`** — add S3 sync: download `token.json` from S3 to `/tmp` on cold start; after any token refresh, re-upload to S3. `auth.py`'s interactive OAuth flow itself **cannot run in Lambda** (needs a browser redirect) — it stays a local/manual one-time bootstrap step (see §7, Phase 1).
- **`src/logger.py`** — file handler should write to `/tmp/pipeline.log` in Lambda (not `data/`), and console output already flows to CloudWatch automatically. `readLogTail()` used by `sendFailureAlert` keeps working as-is since it only needs the current invocation's own log file.
- **`CLAUDE.md`** — once this lands, update the "Deployment target" line, the Phase 3 checklist, and the Component Connections diagram to reflect Lambda + EventBridge instead of cron + Ubuntu.

No changes needed to `summarizer.py`, `tts.py`'s core logic, or `mailer.py` — their logic is transport-agnostic.

## 6. AWS resources (new)

| Resource | Purpose |
|---|---|
| ECR repository | Stores the Lambda container image |
| Lambda function (container image type) | Runs the pipeline |
| IAM execution role | CloudWatch Logs write, S3 read/write on the token bucket, SSM `GetParameter` |
| IAM OIDC deploy role (trust = `token.actions.githubusercontent.com`, scoped to this repo) | Used by GitHub Actions — least privilege: ECR push + `lambda:UpdateFunctionCode` only |
| S3 bucket (small, versioned) | Holds `token.json` and (optionally) `credentials.json` |
| SSM Parameter Store entries (`SecureString`) | `ANTHROPIC_API_KEY`, `SMTP_PASSWORD`, others from `.env.example` |
| EventBridge Scheduler rule | Monday 07:00 (pick timezone explicitly — EventBridge cron is UTC) trigger |
| CloudWatch Log group | Retention policy (e.g. 30 days) for Lambda logs |

## 7. Migration phases

- [ ] **Phase 1 — Bootstrap (manual, one-time)**
  - [ ] Initialize git repo, push to GitHub (currently no `.git` exists)
  - [ ] Run `auth.py` locally as today to produce a valid `token.json`
  - [ ] Create S3 bucket, upload `token.json` (and `credentials.json` if going that route)
  - [ ] Create SSM parameters for all `.env` secrets
- [ ] **Phase 2 — Lambda-compatible image**
  - [ ] Fork `Dockerfile` to Lambda base image, resolve `ffmpeg`/`piper` availability on Amazon Linux
  - [ ] Write `src/lambda_handler.py`
  - [ ] Update `config.py` to read from SSM in Lambda, `.env` locally
  - [ ] Update `gmail_client.py`/`auth.py` for S3 token sync
  - [ ] Test the image locally with the [Lambda Runtime Interface Emulator](https://github.com/aws/aws-lambda-runtime-interface-emulator) before ever pushing to AWS
- [ ] **Phase 3 — Infra (Terraform)**
  - [ ] `ecr.tf`, `iam.tf`, `lambda.tf`, `s3.tf`, `ssm.tf`, `eventbridge.tf`
  - [ ] `terraform apply` manually once to stand up the first version
- [ ] **Phase 4 — CI/CD (GitHub Actions)**
  - [ ] Add OIDC trust relationship + deploy role (via Terraform or console)
  - [ ] Add `.github/workflows/deploy.yml` (§8)
  - [ ] Store the deploy role ARN + AWS region as GitHub repo **variables** (not secrets — the ARN isn't sensitive)
- [ ] **Phase 5 — Cutover**
  - [ ] Run the Lambda manually (test invoke) for 1–2 cycles in parallel with the existing on-prem cron, compare output
  - [ ] Disable the Ubuntu cron job once Lambda output is verified for 2+ consecutive Mondays
  - [ ] Update `CLAUDE.md` Progress/Known Issues sections to match

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

## 9. Cost estimate (rough)

Weekly, few-minute invocation: Lambda compute + ECR storage + S3 + SSM + CloudWatch Logs all sit comfortably in the AWS free tier or amount to **well under $1–2/month**. The dominant ongoing spend stays the Anthropic API usage, unchanged by this migration.

## 10. Open questions / risks

- **Timeout/memory sizing**: unknown until measured — recommend a manual test invoke with generous settings (e.g. 1024–2048 MB memory, 300s timeout) first, then tune down based on actual CloudWatch duration/memory-used metrics. Lambda hard cap is 15 min regardless.
- **`ffmpeg` on Amazon Linux 2023**: needs a static-binary approach, not `apt-get` — flag this as the highest-risk unknown in Phase 2, test it early.
- **Piper binary architecture**: confirm the release binary matches whichever Lambda architecture (x86_64 or arm64) you choose before committing to arm64's cost savings.
- **Ephemeral storage**: default `/tmp` is 512MB; check actual `briefing.mp3` + intermediate WAV size (the existing `data/briefing.mp3` is ~3.7MB, so default should be plenty, but confirm) and bump `EphemeralStorage` config if needed.
- **Timezone for the Monday 07:00 trigger**: EventBridge Scheduler cron expressions are UTC — pick and document the intended timezone explicitly (the current Ubuntu cron implicitly used server-local time).
