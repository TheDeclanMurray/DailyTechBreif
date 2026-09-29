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

- **(2026-08-31) `lambda_timeout_seconds` raised from `300` to `600`** — a normal run's real
  wall-clock time (Gmail fetch → Claude summarization → piper/ffmpeg TTS → SMTP) was landing at
  ~300–311 seconds, right at the old 300s Lambda timeout, so a run could complete and deliver the
  email but still get marked `Status: timeout` by Lambda itself, triggering an EventBridge
  Scheduler retry and a duplicate email — see ISSUES-ENCOUNTERED.md's 2026-08-31 entry. 600s
  gives roughly 2x headroom over observed real duration while staying well inside Lambda's
  15-minute (900s) hard cap.

- **(date uncertain — decision predates this log entry; recorded here 2026-08-31 while syncing
  docs) Schedule: `America/Los_Angeles` IANA timezone, not UTC.** `infra/variables.tf`'s
  `schedule_timezone` variable and the comment above it in `infra/eventbridge.tf` explain the
  reasoning already implemented in code: EventBridge Scheduler (the newer dedicated scheduling
  service used here, not classic EventBridge Rules) accepts an explicit
  `schedule_expression_timezone`, so `America/Los_Angeles` is set directly rather than
  hand-converting the Mon–Fri 07:00 cron to UTC. This was never written down as a decision when
  it was made — `docs/ARCHITECTURE.md` still listed the timezone as an open item until this sync.

- **(2026-09-15) Gmail reading moved from the Gmail API (OAuth2) to IMAP + a Gmail App
  Password.** Supersedes the implicit "use the Gmail API" choice baked in since the project
  started, and the 2026-08-28 decision to upgrade the scope to `gmail.modify`. Reason: the OAuth
  approach had no sustainable configuration for an unattended personal pipeline. `gmail.modify`
  is one of Google's **restricted** scopes, which forces a choice between two bad options — leave
  the External consent screen in "Testing" publishing status, where Google expires the refresh
  token after exactly 7 days, or publish to production, which for a restricted scope requires
  full verification: a domain you own and have verified in Search Console, a live homepage and
  privacy policy, and a third-party CASA security assessment billed annually. The first option is
  what was actually running, and it silently killed seven consecutive days of briefings (see
  ISSUES-ENCOUNTERED.md). The second is grossly disproportionate for a cron job reading its
  owner's own inbox. Two escape hatches were checked and ruled out: narrowing the scope doesn't
  help (`gmail.readonly` is also restricted, and the only non-restricted Gmail scopes —
  `gmail.metadata`, `gmail.labels` — can't read message bodies, which is the entire job), and
  `User type: Internal` isn't available because the mailbox is a consumer `@gmail.com` account,
  not a Workspace one. IMAP with an App Password has no consent screen, no publishing status, no
  verification, and no expiry; it's also the *same credential* `src/mailer.py` already used for
  SMTP delivery on this same account, which is why sending never broke while reading did.
  Trade-offs accepted: App Passwords require 2-Step Verification on the account, and Google could
  in principle deprecate them (no announced end date, and they remain the supported path for
  IMAP/SMTP on consumer accounts). Gmail's IMAP extensions preserved the existing behaviour
  almost exactly — `X-GM-RAW` keeps `buildSearchQuery()`'s Gmail search syntax unchanged,
  `X-GM-LABELS` applies the same `tech-briefing/processed` label, and `X-GM-MSGID` replaces the
  API's message id as a stable key. Net deletion: `src/auth.py`, the `auth` Compose service, the
  `GMAIL_TOKEN_JSON` SSM parameter, the execution role's `ssm:PutParameter` permission, and four
  `google-auth`/`google-api-python-client` dependencies (`imaplib` and `email` are stdlib).

- **(2026-09-15) EventBridge Scheduler retries pinned to zero.** The Lambda target in
  `infra/eventbridge.tf` had no `retry_policy` block, so it inherited EventBridge Scheduler's
  default of **185 retry attempts** over 24 hours. That default is actively harmful here: the
  pipeline is not idempotent past the point where `sendBriefing()` succeeds, and `main.py` emails
  a failure alert on every failed run — so a retried run means either a duplicate briefing or a
  burst of alert emails. This is the true root cause of the 2026-08-31 duplicate-briefing bug,
  which was diagnosed correctly (a run hit the 300s timeout after delivering) but fixed only at
  the symptom (raising `lambda_timeout_seconds` to 600), leaving the retry behaviour in place to
  fire again on any other failure. Set `maximum_retry_attempts = 0`. Failures are still surfaced,
  just not by retrying: `src/lambda_handler.py` now raises, which increments the Lambda `Errors`
  metric and trips the CloudWatch alarm. A single missed briefing is cheap to absorb —
  `markEmailsAsProcessed()` only labels after a successful delivery, so the next run picks the
  same emails up.

- **(2026-09-28) TTS pipeline changed to stream piper PCM directly into ffmpeg** — previously
  piper wrote a full WAV to a `NamedTemporaryFile` and ffmpeg read that file; both processes held
  their audio in memory simultaneously, driving peak Lambda memory to 1,242 MB of the 1,536 MB
  ceiling. Changed to `piper --output-raw` (headerless s16le PCM to stdout) piped directly into
  ffmpeg stdin with explicit format hints (`-f s16le -ar 22050 -ac 1` matching
  `en_GB-jenny_dioco-medium`'s config). Trade-off: the PCM format constants (`PIPER_SAMPLE_RATE`,
  `PIPER_CHANNELS` in `src/tts.py`) are model-specific and must be updated if `TTS_VOICE` ever
  changes. The temp file and cleanup block are gone.
