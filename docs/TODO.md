# TODO

Active items only — this is not a history. Once something is actually done, remove it (a note
worth keeping that it happened belongs in `CLAUDE.md`'s Progress section or `docs/DECISIONS.md`,
not here). Add the date an item is opened.

- [ ] **(2026-08-26) Commit and push all the local-only work, then set `AWS_DEPLOY_ROLE_ARN`** —
  `git log` still shows only the two commits from 2026-08-24. Everything since — the real content
  of every `infra/*.tf` file, `.github/workflows/deploy.yml`, `infra/.terraform.lock.hcl`, the
  `--service-ports` fixes to `src/auth.py`/`src/gmail_client.py`, and today's Lambda-functionality
  fix (`src/lambda_handler.py`, the Lambda-base `Dockerfile`, SSM-aware `config.py`/`logger.py`) —
  exists only on this machine. This matters more than usual right now because the AWS resources
  described by that uncommitted Terraform are already live: there's no version-controlled record
  of what actually created them, and the Lambda is currently running an old broken image (see
  `docs/ISSUES-ENCOUNTERED.md`). Push, then set `AWS_DEPLOY_ROLE_ARN` as a GitHub Actions repo
  **variable** (Settings → Secrets and variables → Actions → Variables — not a secret, the ARN
  isn't sensitive): `arn:aws:iam::137068240045:role/daily-tech-brief-github-deploy` (from
  `terraform output github_deploy_role_arn`). `AWS_REGION`/`ECR_REPOSITORY`/`LAMBDA_FUNCTION_NAME`
  are already set (2026-08-24) — this is the only one still missing, and without it the `deploy`
  job's OIDC auth step fails immediately.

- [ ] **(2026-08-26) Add a backstop alert for crashes the pipeline's own alerting can't catch** —
  `sendFailureAlert()` only runs from inside `main.py`'s `try/except`. The current crash happens
  at import time, before that block is ever reached, so two full days of failed runs produced zero
  notification to anyone. Once the item above is fixed this exact case goes away, but the same gap
  would reopen for any future container-init-time failure. Consider a CloudWatch Alarm on the
  Lambda's `Errors` metric (→ SNS → email) as a defense-in-depth backstop that doesn't depend on
  the pipeline's own code running at all.

- [ ] **(2026-08-21) Fix prompt caching on the system prompt** — [src/summarizer.py](../src/summarizer.py)
  sends the ~700-word `SYSTEM_PROMPT` in the `system` field with a comment claiming Claude caches
  it automatically after the first call. That's incorrect: Anthropic prompt caching only applies
  to blocks with an explicit `cache_control: {"type": "ephemeral"}` breakpoint. Right now only the
  daily email content (the user turn) is cached — the large static system prompt is paid for in
  full on every run. Fix: restructure the `system` field as a list with a `cache_control` block on
  the system prompt text, same pattern already used for the user message. Also update the
  "~90% savings" claim in `src/config.py` and `CLAUDE.md` once fixed to reflect the real number.

- [ ] **(2026-08-24) Tune lambda_memory_mb down from real usage** —
  [infra/variables.tf](../infra/variables.tf) defaults `lambda_memory_mb` to `1536` as a
  starting point (per `docs/AWS_DEPLOYMENT_PLAN.md`), not a measured value. Once the Lambda
  has run for real, check CloudWatch metrics (`Max Memory Used` in the Lambda's monitoring
  tab, or the `REPORT` line in each invocation's logs) and lower the value to match actual
  usage — Lambda bills by memory × duration, so overprovisioning here costs real money for
  no benefit.

- [ ] **(2026-08-24) Mark processed emails so they aren't re-summarized on the next run** —
  [src/gmail_client.py](../src/gmail_client.py)'s `build_query()` (line 79) selects emails purely
  by `after:<lookback_days-ago>`, with no record of which messages a previous run already
  processed. `lookback_days` defaults to `4` specifically so a Monday run still catches
  newsletters sent over the weekend — but now that `infra/variables.tf`'s `schedule_expression`
  runs Mon-Fri, that same 4-day window means Tue-Fri runs re-fetch and re-summarize emails
  already covered by the previous day's run. Fix by having the pipeline mark each email as
  handled once summarized, via one of: (a) mark as read and switch the query to `is:unread`,
  (b) apply a Gmail label (e.g. `tech-briefing/processed`) and exclude labeled messages from the
  query, or (c) move/archive processed messages out of the searched folder. A label is probably
  safest — reversible and inspectable — but any of the three removes the re-processing risk.
  Needs a decision recorded in `docs/DECISIONS.md` once picked, since it changes what the Gmail
  OAuth scope needs to allow (`gmail.readonly` → `gmail.modify` for labeling/marking-read, or add
  the Gmail API's `modify` scope specifically — see `GMAIL_SCOPES` in `src/config.py`).

- [ ] **(2026-08-24) Confirm the ECR lifecycle policy actually deletes images** —
  [infra/ecr.tf](../infra/ecr.tf) now has two rules: expire untagged images after 14 days
  (a safety net — CI tags every push with a unique git SHA, so images rarely go untagged in
  normal operation), and keep only the newest 4 tagged images (active + 3 rollback candidates),
  which is what actually bounds repo growth and naturally retires the `:initial` bootstrap tag.
  Once `infra/` is applied and CI has pushed 5+ builds, confirm in the console/
  `aws ecr describe-images` that older tagged images are actually being expired, not just that
  the policy is attached.

- [ ] **(2026-08-21) Start each run with a clean log instead of appending forever** —
  [src/logger.py](../src/logger.py) opens `logs/pipeline.log` with `FileHandler(..., mode="a")`,
  so the file grows without bound across every run. Not urgent on the deployed cron target (one
  run a week), but locally — running the pipeline repeatedly during development — it balloons
  fast. Fix: truncate the log at the start of each run (`mode="w"`, or an explicit
  `open(LOG_PATH, "w").close()` before attaching the handler) so every run starts clean. If any
  history across runs is still wanted, consider rotating to `pipeline.log.1` before truncating
  instead of just discarding it.
