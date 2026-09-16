# Tech Briefing Pipeline

## Working conventions
- **Don't poll GitHub Actions run status repeatedly after triggering a push.** Confirm the push
  went through, say what's running and roughly how long it should take, then stop and ask the
  user to report back when it finishes (or check once if asked). Established 2026-08-26 after
  repeatedly re-fetching a run's status in a loop — the user would rather check the Actions tab
  themselves and tell me when it's done than have me hammer the API.
- **Run tests via the `test` Docker Compose service, never a host/throwaway venv.**
  `docker compose run --rm test` runs `src/tests/unit_tests.py` in `Dockerfile.test` (plain
  `python:3.12-slim`, no piper/ffmpeg) with `src/` bind-mounted, so no venv is created or needs
  cleanup. Established 2026-08-27 after repeatedly creating a venv on the host to run pytest and
  then deleting it — the container does the same job without the create/delete churn. See "Test
  Files" below for exact commands.

## Overview
Automated daily briefing pipeline. Reads newsletter emails via Gmail IMAP, summarises
them with Claude, converts to MP3 via piper-tts, and emails the MP3 on a weekday (Mon–Fri)
schedule (`cron(0 7 ? * MON-FRI *)` in `infra/variables.tf`).
Stack: Python 3.12, Anthropic SDK, Gmail IMAP (App Password), piper-tts, Docker Compose.
Deployment target: AWS Lambda (container image) + EventBridge Scheduler — see
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the canonical summary and
[docs/DECISIONS.md](docs/DECISIONS.md) for why this replaced the original on-prem
cron plan. Docker Compose (`./run`) remains the local dev/test harness either way.

## File & Folder Structure
```
tech-briefing/
├── docker-compose.yml      # main service + test service (the one-off `auth` service was
│                           # removed 2026-09-15 with the OAuth flow)
├── Dockerfile              # Lambda-compatible base (public.ecr.aws/lambda/python:3.12);
│                           # docker-compose.yml overrides entrypoint/command for local dev
├── Dockerfile.test         # plain python:3.12-slim for the `test` service — no piper/ffmpeg,
│                           # so unit tests don't require building the heavy Lambda image
├── .env                    # secrets — never committed (see .env.example)
├── .env.example            # template for .env
├── .claudeignore           # excludes *.env, credentials.json, token.json
├── .gitignore
├── requirements.txt
├── README.md               # quick-start, points here and at docs/
├── CLAUDE.md               # this file
├── .claude/
│   ├── settings.json       # PreToolUse hooks config
│   └── hooks/
│       ├── block_secrets.py         # blocks reads/leaks of secret-shaped files
│       └── block_dangerous_git.py   # blocks destructive git ops (force-push, reset --hard, etc.)
├── docs/
│   ├── TODO.md             # outstanding follow-ups, e.g. the prompt-caching fix
│   ├── ARCHITECTURE.md    # canonical stack/hosting/IaC/CI-CD summary
│   ├── SCOPE.md           # what this project is and isn't trying to do
│   ├── DECISIONS.md       # running design decisions log
│   ├── ISSUES-ENCOUNTERED.md  # running problems/resolutions log
│   ├── GMAIL_SETUP.md      # step-by-step Google Cloud Console instructions
│   └── AWS_DEPLOYMENT_PLAN.md  # detailed Lambda + GitHub Actions migration plan (infra/ now implements it, see below)
├── infra/                  # Terraform IaC for the AWS Lambda deployment — applied to AWS (2026-08-25),
│                           # deploy CI/CD working since 2026-08-26 — see Known Issues below for the
│                           # current status of the deployed Lambda itself
├── .github/
│   └── workflows/
│       └── deploy.yml      # CI: pytest unit tests -> build/push image to ECR -> update Lambda code
├── logs/
│   └── pipeline.log        # runtime log, gitignored, one run per header-separated block
│                           # (no data/ dir any more — it held credentials.json/token.json for
│                           #  the OAuth flow, both gone since 2026-09-15; the MP3 never touches
│                           #  disk either, see tts.py below)
├── src/
│   ├── __init__.py
│   ├── config.py           # all constants and env vars in one place; SSM-aware when IS_LAMBDA
│   ├── gmail_client.py     # Gmail IMAP: fetch emails from configured senders + label processed
│                           # (no auth.py — the OAuth flow it ran was removed 2026-09-15)
│   ├── summarizer.py       # Claude API: summarise emails into briefing
│   ├── tts.py              # piper-tts + ffmpeg: briefing text -> in-memory MP3 bytes (never
│   │                       # written to disk — see Key Constants below)
│   ├── logger.py           # logging setup; /tmp/pipeline.log in Lambda, logs/pipeline.log locally
│   ├── mailer.py           # SMTP delivery of the briefing + failure alerts
│   ├── main.py             # pipeline entry point -- runPipeline() is shared by __main__ and lambda_handler.py
│   ├── lambda_handler.py   # AWS Lambda entry point: handler(event, context) wraps main.runPipeline()
│   └── tests/
│       ├── unit_tests.py        # pure logic, no external calls
│       └── integration_tests.py # real Gmail + Claude API calls — run manually
```

## Component Connections
```
local dev: ./run (docker compose run tech-briefing)
prod target: EventBridge Scheduler ──▶ Lambda (container image)  [infra applied 2026-08-25; deploy
                                                                    CI/CD working since 2026-08-26;
                                                                    Gmail→Claude→TTS→SMTP confirmed
                                                                    working end-to-end via a real
                                                                    EventBridge-triggered run
                                                                    2026-08-31 -- see Progress below]
  └─▶ lambda_handler.py ──▶ main.runPipeline()
  └─▶ main.py
        ├─▶ gmail_client.py  ──▶ Gmail IMAP  ──▶ emails[]
        ├─▶ summarizer.py    ──▶ Claude API  ──▶ briefing text
        ├─▶ tts.py           ──▶ piper-tts   ──▶ briefing.mp3 (in-memory bytes)
        └─▶ mailer.py        ──▶ SMTP        ──▶ email with MP3
```
All config flows through `src/config.py` — nothing reads `os.environ` directly elsewhere.

## Test Files
- UnitTests: `src/tests/unit_tests.py` — run in the `test` Docker Compose service, not a host
  venv: `docker compose run --rm test`. Uses `Dockerfile.test` (plain `python:3.12-slim`, not
  the heavy Lambda/piper/ffmpeg image) and bind-mounts `src/` so edits run without a rebuild.
  Same command CI runs (see `.github/workflows/deploy.yml`'s `test` job).
- IntegrationTests: `src/tests/integration_tests.py` — requires live Gmail/Claude credentials
  AND a network that permits port 993 (not the office — see Known Issues);
  run manually, not in CI or the `test` service: `python -m pytest src/tests/integration_tests.py -v`

## Progress
- [x] **Diagnosed a week of dead briefings and moved Gmail reading off OAuth to IMAP + App
      Password (2026-09-15)** — user reported briefings broken for about a week. AWS showed the
      Lambda firing on schedule every weekday with `Errors` at 0.0, i.e. every run recorded as a
      success; CloudWatch logs showed each one dying ~1.8s in on `invalid_grant: Token has been
      expired or revoked`. Root cause: the OAuth consent screen sat in "Testing" publishing
      status, where Google expires refresh tokens after exactly 7 days — the token was re-authed
      2026-08-28 and the last successful run was 2026-09-04, to the day. Rather than re-auth
      (worth exactly 7 more days) or pursue verification (a restricted scope needs a domain,
      privacy policy and a paid CASA audit — and `Internal` isn't available on a consumer
      `@gmail.com` account), `src/gmail_client.py` was rewritten onto `imaplib` + the Gmail App
      Password `mailer.py` already used. `X-GM-RAW` keeps `buildSearchQuery()` byte-identical,
      `X-GM-LABELS` keeps the processed-label dedup, `X-GM-MSGID` replaces the API message id.
      Deleted: `src/auth.py`, the `auth` Compose service, the `GMAIL_TOKEN_JSON` SSM parameter,
      the execution role's `ssm:PutParameter` permission, and four google-auth/api-client deps.
      **Also fixed the two things that let this stay silent for a week:** (1)
      `src/lambda_handler.py` returned `{"statusCode": 500}` on failure believing that registered
      as a CloudWatch error — it does not, only a raised exception does, which is why the
      2026-08-28 alarm backstop never fired; it now raises. (2) `infra/eventbridge.tf`'s target
      had no `retry_policy`, inheriting EventBridge Scheduler's default of **185 retries** — with
      a raising handler that would mean 185 pipeline re-runs and 185 alert emails per failure,
      and it is also the true root cause of the 2026-08-31 duplicate-briefing bug that was fixed
      at the symptom (timeout 300→600) rather than the mechanism; pinned to 0. 56 unit tests
      pass. **Not yet verified against the real mailbox** — the office network resets TLS on port
      993, so the IMAP path could not be exercised locally at all; needs a manual
      `aws lambda invoke` after deploy. See `docs/TODO.md` and `docs/ISSUES-ENCOUNTERED.md`.
- [x] **Full pipeline confirmed end to end on a real EventBridge-triggered run, deployed Lambda
      labeling confirmed too, and a duplicate-email bug found and fixed (2026-08-31)** — the
      Mon–Fri 7am scheduled run actually fired via EventBridge (not a manual invoke) and completed
      Gmail → Claude → TTS → SMTP for real, with `markEmailsAsProcessed()` confirmed working on
      the deployed Lambda (`"Marked 5 email(s) as processed"` in CloudWatch), closing out the two
      oldest open TODO items (`docs/TODO.md`'s "confirm full pipeline end to end" and "confirm
      deployed Lambda can label"). Along the way, found a real bug via CloudWatch logs: the user
      got two briefing emails ~5 minutes apart. Root cause: a normal run's wall-clock time
      (~300–311s) was landing right at the Lambda's 300s timeout, so a run could finish and
      deliver the email but still get marked `Status: timeout`, triggering an EventBridge
      Scheduler retry that ran the whole pipeline again and sent a second email. Fixed by raising
      `lambda_timeout_seconds` from `300` to `600` in `infra/variables.tf` and applying — see
      `docs/ISSUES-ENCOUNTERED.md` and `docs/DECISIONS.md` for the full trail. While applying,
      also discovered the 2026-08-28 CloudWatch alarm's SNS email subscription had never actually
      been created (state drift) — created it now via the same `terraform apply`, and confirmed
      (subscriber clicked the confirmation link the same day) — the alarm backstop is fully live.
- [x] **Gmail label-based processed-tracking, code side (2026-08-28)** — `GMAIL_SCOPES` upgraded
      to `gmail.modify`; `gmail_client.py` gained `getOrCreateProcessedLabel()`,
      `markMessageProcessed()`, and `markEmailsAsProcessed()`; `buildSearchQuery()` now excludes
      `-label:"tech-briefing/processed"`; `main.py` calls `markEmailsAsProcessed()` only after
      `sendBriefing()` succeeds, so a failure earlier in the pipeline leaves emails unlabeled and
      eligible for the next run. 7 new unit tests added, all 44 passing via `docker compose run
      --rm test`. **Re-auth done and labeling confirmed working end to end locally (2026-08-28)**
      — local `docker compose run --rm --service-ports auth` completed with the new `gmail.modify`
      scope (verified via `token.json`'s `scopes` field); a standalone verification run against
      the real Gmail account (fetch → label 11 real unprocessed emails → re-fetch) confirmed the
      `tech-briefing/processed` label was created and all 11 were excluded from the next query,
      with zero Claude/TTS/SMTP calls made. **Token pushed to SSM (2026-08-28)** — the re-authed
      `gmail.modify` token is now live in the `GMAIL_TOKEN_JSON` SSM parameter. **Not yet done:
      the labeling code itself hasn't shipped to Lambda yet** (this commit is the first push of
      it), so confirming the deployed Lambda can label still needs one more manual invoke after
      `deploy` runs — see Known Issues below and `docs/TODO.md`. Note: the
      first attempt at this local verification looked successful (real email sent, exit code 0)
      but had actually run a stale pre-edit `tech-briefing` image and never touched the labeling
      code at all — see `docs/ISSUES-ENCOUNTERED.md`'s 2026-08-28 entry for the full diagnosis.
- [x] **CloudWatch Alarm backstop on Lambda `Errors` → SNS → email (2026-08-28)** —
      `infra/alarms.tf` added and applied: an `aws_cloudwatch_metric_alarm` on the Lambda's
      `Errors` metric (any error in a 5-minute window trips it) publishes to a new SNS topic,
      which emails `var.my_email`. Exists specifically to catch the failure mode
      `sendFailureAlert()` can't — a crash before `main.py`'s `try/except` is ever reached (e.g.
      import-time or container-init failures), which is what silently ate two days of runs
      earlier. **Confirmed live 2026-08-31** — see the entry at the top of this section for the
      state-drift/recreate/confirm trail.
- [x] **`LOOKBACK_DAYS` default synced to 4 across the codebase (2026-08-28)** — the real value in
      use (both local `.env` and `infra/variables.tf`'s `lookback_days`) has been `4` for a while,
      but `src/config.py`'s fallback default, `.env.example`, and `CLAUDE.md` still said `1`.
      Updated all three to `4` so a missing env var now behaves the same as the value actually
      running everywhere; not a behavior change to any deployed/local config, just removing
      misleading fallback/docs drift.
- [x] Project structure and Docker Compose setup
- [x] .claudeignore, .gitignore, .env.example
- [x] requirements.txt
- [x] GMAIL_SETUP.md — step-by-step Google Cloud Console guide
- [x] src/config.py — centralised constants and env var loading
- [x] src/auth.py — one-time OAuth2 flow
- [x] src/gmail_client.py — Gmail fetch (Phase 1)
- [x] src/summarizer.py — Claude API summarisation with prompt caching (Phase 1)
- [x] src/main.py — pipeline entry point (Phase 1: print to console)
- [x] src/tests/unit_tests.py — unit coverage for query builder, text extractor, prompt formatter, tts guard clauses
- [x] src/tests/integration_tests.py — stubs for Gmail + Claude live tests
- [x] **Phase 2**: src/tts.py — piper-tts + ffmpeg, WAV -> MP3
- [x] **Phase 2**: Dockerfile updated — piper binary + lessac-high voice model baked in
- [x] **Phase 3**: src/mailer.py — SMTP email with MP3 attachment (implemented 2026-08-24;
      confirmed working end-to-end via a live local run 2026-08-25 — see below)
- [x] `.github/workflows/deploy.yml` — test job (pytest) gates deploy job (build/push
      image to ECR via OIDC, `aws lambda update-function-code`) — written 2026-08-24, pushed to
      GitHub along with all of `infra/`'s real resource definitions 2026-08-26 (see the entries
      below for what happened once it actually ran)
- [x] **`infra/` applied to AWS (2026-08-25)** — ECR repo, Lambda function, both IAM roles
      (execution + GitHub OIDC deploy), EventBridge Scheduler all live and verified via the AWS
      CLI. **Correction (2026-08-26): the "all 3 SSM secrets seeded" claim in this entry's
      original version was wrong** — they were still the Terraform-applied `REPLACE_ME`
      placeholder until 2026-08-26; see the fix below and `docs/ISSUES-ENCOUNTERED.md`.
- [x] **Made the Lambda actually functional end to end (2026-08-26)** — `src/lambda_handler.py`
      added; Dockerfile switched to `public.ecr.aws/lambda/python:3.12`; `src/config.py` reads
      `ANTHROPIC_API_KEY`/`SMTP_PASSWORD`/the Gmail token from SSM when `IS_LAMBDA`, and the
      refreshed Gmail token is now written back to SSM too (`persistGmailToken()`); `src/logger.py`
      uses `/tmp/pipeline.log` in Lambda. Pushed to `main`, `AWS_DEPLOY_ROLE_ARN` set as a repo
      variable — but the `deploy` job's OIDC auth then failed on every attempt
      (`AccessDenied: sts:AssumeRoleWithWebIdentity`) because GitHub's real `sub` claim includes
      immutable owner/repo IDs the trust policy wasn't scoped to; found via CloudTrail, fixed in
      `infra/iam.tf`, applied locally, pushed — `deploy` job then succeeded. Two more real bugs
      only surfaced via an actual `aws lambda invoke` against the deployed function: the three
      SSM secrets were still placeholders (see above), and `src/tts.py`'s `FFMPEG_BINARY` was
      still hardcoded to the old base image's `/usr/bin/ffmpeg` instead of the new image's
      `/usr/local/bin/ffmpeg`. Both fixed 2026-08-26. **Correction: this entry originally claimed
      "confirmed working end to end" here — that was premature.** The invoke that confirmed the
      ffmpeg fix actually crashed one step later, at `TTS_OUTPUT_PATH` (see the two items below);
      real Gmail → Claude → TTS → SMTP delivery on Lambda, with an actual email sent, still hasn't
      been confirmed as of this entry — see `docs/ISSUES-ENCOUNTERED.md` for the full trail and
      `docs/TODO.md` for what's still open. Not yet confirmed against an actual
      EventBridge-triggered (as opposed to manually invoked) run either.
- [x] **`deploy` job confirmed actually working end to end (2026-08-26)** — after the OIDC fix
      above, `deploy` succeeded (build → push to ECR → update Lambda code) for the first time.
- [x] **Two more real bugs found via manual `aws lambda invoke` (2026-08-27)**:
      (1) `TTS_OUTPUT_PATH` in `src/config.py` was still a relative `data/briefing.mp3` path —
      same root cause as the original `logs/` crash, fixed 2026-08-26 (`cd55232`), **but that
      push's own `deploy` build then failed** (see next item), so this fix was not actually live
      on the deployed Lambda as of this entry. (2) The `deploy` job's Docker build started
      failing separately: `wget` downloading the static ffmpeg tarball from johnvansickle.com got
      blocked/challenged by that host specifically for GitHub Actions runner IPs (confirmed the
      same URL works fine from a normal client) — fixed 2026-08-27 by switching to
      BtbN/FFmpeg-Builds' GitHub-hosted release assets instead (`152fb44`), verified via a real
      local `docker compose build` + running the extracted binary inside the built image. This
      push carries both fixes forward. **Resolved 2026-08-31**: this `deploy` run's fixes did
      ship, and the pipeline is now confirmed completing end to end (Gmail → Claude → TTS → SMTP
      with a delivered MP3) on a real EventBridge-triggered run — see the entry at the top of this
      section.
- [x] Project structure aligned to standard layout (`docs/`, `logs/`, `src/tests/`) — 2026-08-21
- [x] `.claude/hooks/block_secrets.py` + `block_dangerous_git.py` installed — 2026-08-21
- [x] `infra/*.tf` implementing `docs/AWS_DEPLOYMENT_PLAN.md` (Lambda, ECR, IAM incl. GitHub
      OIDC deploy role, SSM secrets, EventBridge Scheduler) — written 2026-08-24, applied to AWS
      2026-08-25 (see the entry above)
- [x] **Full local pipeline validated end-to-end via Docker Compose (2026-08-25)** — real
      Gmail fetch (9 emails) → Claude summarisation → piper-tts/ffmpeg → MP3 → SMTP delivery
      to both recipients, all live, no mocks. Found and fixed a real bug along the way: every
      reference to the `auth` service's run command was missing `--service-ports`, so
      `docker compose run --rm auth` never published port 8080 and the OAuth redirect always
      failed with "localhost refused to connect" — see
      [ISSUES-ENCOUNTERED.md](docs/ISSUES-ENCOUNTERED.md) for the full diagnosis and the fix
      across all 6 affected files. This was the last unverified assumption before moving on to
      `terraform apply` — the application code itself is confirmed sound end-to-end.

## Key Constants & Config
All in `src/config.py`:
- `IMAP_HOST`/`IMAP_PORT` = `imap.gmail.com`/`993`
- `IMAP_USER`/`IMAP_PASSWORD` = default to `SMTP_USER`/`SMTP_PASSWORD` (same mailbox, same Gmail
  App Password covers both reading and sending); override in `.env` only to split them
- No `CREDENTIALS_PATH`/`TOKEN_PATH`/`GMAIL_SCOPES` — removed 2026-09-15 with the OAuth flow
- `PROCESSED_LABEL_NAME` = `"tech-briefing/processed"` — Gmail label applied to a message once
  summarized, so it's excluded from the next run's search query (applied via IMAP's
  `+X-GM-LABELS` store; messages are keyed by the stable `X-GM-MSGID`, not IMAP UIDs)
- `CLAUDE_MODEL`      = `claude-sonnet-4-6`
- `MAX_RESULTS_PER_SENDER` = `5` (in gmail_client.py)
- `MAX_CONTENT_CHARS` = `150_000` (in summarizer.py — truncation limit)
- `LOOKBACK_DAYS`     = from `.env` locally / Terraform's `lookback_days` var on Lambda, default `4`
  (kept in sync between `src/config.py`'s fallback, `.env.example`, and `infra/variables.tf`)
- `NEWSLETTER_SENDERS`= from `.env`, comma-separated
- `TTS_VOICE`         = from `.env`, default `en_GB-jenny_dioco-medium` (must match a model baked
  into the Dockerfile)
- `TTS_SPEED`         = from `.env`, default `1.5` (ffmpeg `atempo` multiplier, 0.5–2.0)
- No `TTS_OUTPUT_PATH` — removed 2026-08-27; the MP3 is never written to disk, ffmpeg streams
  it straight to memory as bytes (see `src/tts.py`), sidestepping the Lambda
  read-only-filesystem problem entirely rather than routing around it with a `/tmp` path
- `IS_LAMBDA`         = `bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME"))` — set automatically by the
  Lambda runtime; gates whether secrets/paths come from `.env`/local dirs or SSM/`/tmp` (see
  Known Issues below)
- `SSM_PARAMETER_PREFIX` = from the `SSM_PARAMETER_PREFIX` Lambda env var (Terraform-set), e.g.
  `/daily-tech-brief`

## Known Issues & Decisions
- **Lambda timeout headroom (fixed 2026-08-31)**: `lambda_timeout_seconds` was `300`, right at a
  normal run's real wall-clock time (~300–311s), so a run could complete and deliver the email but
  still get marked `Status: timeout`, triggering an EventBridge Scheduler retry and a duplicate
  email. Raised to `600` — see `docs/ISSUES-ENCOUNTERED.md` and `docs/DECISIONS.md`'s 2026-08-31
  entries for the full trail.
- **Gmail auth is an App Password, not OAuth (changed 2026-09-15)**: `gmail.modify` is a Google
  *restricted* scope, so an External consent screen had to either stay in "Testing" mode — where
  Google expires the refresh token after exactly 7 days — or pass a paid verification audit. The
  Testing-mode expiry silently killed seven consecutive days of briefings (2026-09-07 → 09-15).
  Reading moved to IMAP with the same Gmail App Password `mailer.py` already used for SMTP. No
  consent screen, no `token.json`, no expiry, no one-off `auth` step. See `docs/DECISIONS.md`.
- **The office network blocks IMAPS (port 993)**, so the pipeline cannot reach Gmail from the
  Cobaltix network — TCP connects, then TLS is reset. Port 587 (SMTP submission) is allowed,
  which is why sending always worked locally. Local end-to-end testing requires a different
  network; deployed Lambda runs are unaffected (no VPC, unrestricted AWS egress).
- **piper-tts + ffmpeg (Phase 2)**: piper generates a WAV at natural speed (voice model
  `en_GB-jenny_dioco-medium` by default, downloaded from HuggingFace at build time and baked into
  the image — changing `TTS_VOICE` requires updating the model wget URL in the Dockerfile and
  rebuilding); ffmpeg then applies the speed change via its `atempo` filter (`TTS_SPEED`, default
  `1.5`), which preserves pitch — piper's own `--length-scale` doesn't. ffmpeg itself is a static
  binary baked into the image (not available via AL2023's `dnf` repos) — see
  `docs/DECISIONS.md`/`docs/ISSUES-ENCOUNTERED.md` for why that source changed twice.
- **Prompt caching**: The Claude API call in `summarizer.py` marks the large user content
  block as `ephemeral` cache. This saves ~90% on repeated runs with similar content.
  The static `SYSTEM_PROMPT` is NOT currently cached (needs its own `cache_control`
  breakpoint) — tracked in [docs/TODO.md](docs/TODO.md).
- **SMTP password (Phase 3)**: Use a Gmail App Password, not your account password.
  Generate one at myaccount.google.com → Security → App passwords.
- **Secret/destructive-git protection**: `.claude/hooks/block_secrets.py` and
  `block_dangerous_git.py` run as `PreToolUse` hooks (see `.claude/settings.json`) on every
  tool call — they block reads of secret-shaped files and destructive git operations.
- **Deployed Lambda was non-functional; getting it working has been a long chain of fixes, each
  only found by testing against the real thing** (`infra/` was applied to AWS on 2026-08-25 before
  the code-side half of the migration was actually done, so every scheduled run since crashed at
  import time with `OSError: [Errno 30] Read-only file system: 'logs'`, before `sendFailureAlert()`
  could ever run). Full trail in `docs/ISSUES-ENCOUNTERED.md`, in order: (1) the core
  handler/Dockerfile/config/logging fix; (2) two AL2023 Docker build failures (missing `gzip`,
  missing `ldconfig`); (3) GitHub Actions repo values added as **secrets** instead of
  **variables** (`deploy.yml` reads `vars.*` only); (4) the OIDC trust policy's `sub` condition
  not matching GitHub's real token, which includes immutable owner/repo IDs — found via
  CloudTrail; (5) the three SSM secrets still holding Terraform's `REPLACE_ME` placeholder; (6)
  `src/tts.py`'s `FFMPEG_BINARY` still pointing at the old base image's path; (7)
  `TTS_OUTPUT_PATH` in `src/config.py` still a relative path, same class of bug as the original
  `logs/` crash; (8) the `deploy` job's own Docker build separately started failing because
  johnvansickle.com (the static ffmpeg source) blocks/challenges GitHub Actions runner IPs —
  switched to BtbN/FFmpeg-Builds' GitHub-hosted release assets instead. **Resolved 2026-08-31**:
  fix (8)'s `deploy` run succeeded, and real Gmail → Claude → TTS → SMTP delivery on Lambda, with
  an actual email sent, is now confirmed end to end via a real EventBridge-triggered run — see the
  Progress entry at the top of this file for that date.
