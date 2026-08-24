# Decisions Log

What was decided, and when. Append-only — if a decision later changes, add a new entry that
says so and points back at the one it supersedes; don't rewrite history.

- **(circa 2026-06, formalized 2026-08-21) Deployment target: AWS Lambda (container image) +
  EventBridge Scheduler**, replacing the originally-planned on-prem Ubuntu + cron deployment.
  Reason: piper-tts and ffmpeg are large non-pip artifacts the Dockerfile already bundles as a
  container image; the job itself is a few-minute weekly batch, comfortably inside Lambda's
  15-minute cap, so Lambda is cheaper and simpler than a Fargate scheduled task. See
  [AWS_DEPLOYMENT_PLAN.md §4](AWS_DEPLOYMENT_PLAN.md#4-key-decisions).

- **(2026-08-21) IaC tool: Terraform**, definitions in `infra/` at the project root, separate
  from `src/`. Chosen over AWS SAM/CDK for being cloud-agnostic and mainstream; user confirmed
  this explicitly during architecture planning on 2026-08-21.

- **(2026-08-21) CI/CD: GitHub Actions.** A `test` job (pytest against
  `src/tests/unit_tests.py`) gates a `deploy` job that builds/pushes the container image and
  updates the Lambda. The integration test suite (`src/tests/integration_tests.py`) needs live
  credentials and deliberately stays out of CI, run manually only.

- **(2026-08-21) GitHub → AWS auth: OIDC federation**, not static IAM access keys. No long-lived
  AWS credentials get stored in GitHub secrets; the deploy role ARN and region are stored as
  GitHub Actions **variables** (not secrets) since the ARN itself isn't sensitive.

- **(2026-08-21) Repo: `https://github.com/TheDeclanMurray/DailyTechBreif.git`.** Project will
  be pushed here. Git init + first push hasn't happened yet — the authentication method for the
  push is still open, see [ISSUES-ENCOUNTERED.md](ISSUES-ENCOUNTERED.md).

- **(circa 2026-06, formalized 2026-08-21) OAuth token persistence: S3 object**, not Secrets
  Manager. Lambda's filesystem is ephemeral across cold starts, so `token.json` must live
  somewhere durable and get re-uploaded after any refresh; S3 is simpler for a single blob than
  paying Secrets Manager's per-secret charge for something that doesn't need rotation.

- **(circa 2026-06, formalized 2026-08-21) App secrets (Anthropic key, SMTP password, etc.):
  SSM Parameter Store, `SecureString` type**, not Secrets Manager — free, sufficient for this
  scale, native `boto3` support.
