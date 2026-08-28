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
  **Superseded — see the entry below.**

- **(date uncertain — decision predates this log entry, `infra/s3.tf` was already gone by
  2026-08-25; recorded here 2026-08-26 while syncing docs) OAuth token persistence changed from
  an S3 object to an SSM `SecureString` parameter instead**, per the comment at the top of
  `infra/ssm.tf`: `token.json` already fits comfortably inside SSM's 4KB standard-parameter
  limit, so a dedicated S3 bucket + IAM policy for a single blob was unnecessary — one more SSM
  parameter alongside the other two secrets is simpler. `infra/s3.tf` was deleted accordingly.
  This log wasn't updated at the time the change was made, which is exactly the kind of drift
  this file's append-only convention exists to prevent — noting it now for the record.

- **(2026-08-21) App secrets (Anthropic key, SMTP password, etc.):
  SSM Parameter Store, `SecureString` type**, not Secrets Manager — free, sufficient for this
  scale, native `boto3` support.

- **(2026-08-26) Dockerfile base switched to `public.ecr.aws/lambda/python:3.12`** (from
  `python:3.12-slim`) as part of making the deployed Lambda actually functional — see
  `docs/ISSUES-ENCOUNTERED.md` for the crash this fixes. One Dockerfile now serves both local
  dev and Lambda: `docker-compose.yml` overrides `entrypoint`/`command` to run `python3.12 -m
  src.main` directly for local `docker compose run`, while the image's own `CMD` (`src.lambda_handler.handler`)
  only ever executes for real inside Lambda. Chosen over maintaining two separate Dockerfiles to
  avoid the two builds silently drifting apart.

- **(2026-08-26) ffmpeg installed via a static build (johnvansickle.com), not `dnf`** — Amazon
  Linux 2023's default repos (the new base image's OS) don't carry ffmpeg, likely a licensing
  reason (its GPL codecs). A self-contained static binary has no shared-library dependencies of
  its own, so it sidesteps the question of what's available in AL2023's repos entirely.

- **(2026-08-26) Dropped the separate `libespeak-ng1` system-package install for piper-tts** —
  confirmed the piper release tarball already bundles `libespeak-ng.so.1` alongside the piper
  binary, so no system package is needed on either base image. Also switched from writing
  `/etc/ld.so.conf.d/piper.conf` + running `ldconfig` to setting `LD_LIBRARY_PATH` directly, since
  this Lambda base image doesn't ship the `ldconfig` binary at all (build failed on it, see
  `docs/ISSUES-ENCOUNTERED.md`) — an env var achieves the same dynamic-linker result without
  depending on a binary that may or may not be present.

- **(2026-08-26) GitHub OIDC trust policy scoped to immutable owner/repo IDs, not just names**
  — `infra/iam.tf`'s `sub` condition now reads `repo:${owner}@${owner_id}/${repo}@${repo_id}:ref:...`
  instead of just `repo:${owner}/${repo}:ref:...`, because that's what GitHub's actual token
  contains (confirmed via CloudTrail — see `docs/ISSUES-ENCOUNTERED.md`). Kept the IDs as
  explicit `terraform.tfvars`-free defaults in `infra/variables.tf` rather than a `StringLike`
  wildcard (e.g. `OWNER@*/REPO@*`) — pinning the real IDs is strictly tighter and is exactly what
  this GitHub feature is for (surviving/rejecting a rename or repo recreation correctly), and the
  IDs are effectively permanent for the life of the repo.

- **(2026-08-28) Gmail OAuth scope upgraded from `gmail.readonly` to `gmail.modify`, and
  re-processing avoided via a Gmail label rather than marking messages read or moving them** —
  resolves the Tue-Fri re-summarization problem noted in `docs/TODO.md` (2026-08-24). Chose
  labeling (`tech-briefing/processed`, applied via `gmail_client.markEmailsAsProcessed()`) over
  the other two options considered — mark-as-read + `is:unread` query, or archive/move out of the
  searched folder — because it's reversible and inspectable in the Gmail UI without touching the
  user's own read/unread state or mailbox organization. The label is applied only AFTER a
  briefing is successfully delivered (`main.py` step 6, not inside `fetchNewsletterEmails()`), so
  a failure earlier in the pipeline leaves the source emails unlabeled and eligible for the next
  run instead of silently losing them. `gmail.modify` is required because Gmail's API doesn't
  allow adding labels under `gmail.readonly`. Any `token.json` issued before this change must be
  regenerated via the auth flow — see `docs/GMAIL_SETUP.md`'s upgrade section.

- **(2026-08-26) Gmail token refresh writes back to SSM, not just the local file** — added
  `config.persistGmailToken()`, called from `gmail_client.py`'s refresh path, which writes to
  `TOKEN_PATH` locally always and additionally `ssm:PutParameter`s the refreshed token when
  `IS_LAMBDA`. Without this, every Lambda cold start would keep reusing the pre-refresh token
  from SSM, forcing a redundant refresh call on every single invocation. This is what the
  `ignore_changes = [value]` comment on the `gmail_token` SSM parameter in `infra/ssm.tf` was
  already anticipating — it just wasn't implemented in code yet.

- **(2026-08-27, commit `ab167b0`) MP3 is never written to disk anywhere, including `/tmp`** —
  a scheduled Lambda run had crashed with `OSError: Read-only file system: 'data'` because
  `TTS_OUTPUT_PATH` was still a relative path. Rather than just redirecting that write to
  `/tmp` (matching `LOG_PATH`'s existing pattern), removed the disk write entirely: the MP3 is
  only ever attached to the outgoing email and never read again afterward, so there was no
  reason to persist it anywhere in the first place. `src/tts.py`'s `convertToMp3()` now has
  ffmpeg stream the encoded MP3 to stdout and returns it as `bytes`; `mailer.py`/`main.py` were
  updated to pass bytes straight through. `TTS_OUTPUT_PATH` was removed from `src/config.py`
  entirely. This log wasn't updated at the time the change was made — noting it now for the
  record (see `docs/ISSUES-ENCOUNTERED.md`'s 2026-08-26 `TTS_OUTPUT_PATH` entry and
  `AWS_DEPLOYMENT_PLAN.md`'s Open Questions for what this superseded).

- **(2026-08-28) CloudWatch Alarm on the Lambda's `Errors` metric added as a backstop** —
  `infra/alarms.tf`: an `aws_sns_topic` + `aws_sns_topic_subscription` (email, `var.my_email`)
  + `aws_cloudwatch_metric_alarm` watching `AWS/Lambda` `Errors` for the function. Exists because
  `sendFailureAlert()` only ever runs from inside `main.py`'s own `try/except`, so it can't catch
  a crash before that point is reached (import-time errors, container-init failures) — exactly
  the failure mode that silently ate two days of runs in the 2026-08-26 incident (see
  ISSUES-ENCOUNTERED.md). This alarm doesn't depend on the pipeline's own code running at all.
