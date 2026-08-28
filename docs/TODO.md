# TODO

Active items only — this is not a history. Once something is actually done, remove it (a note
worth keeping that it happened belongs in `CLAUDE.md`'s Progress section or `docs/DECISIONS.md`,
not here). Add the date an item is opened.

- [ ] **(2026-08-28) Confirm the CloudWatch alarm email subscription got confirmed** —
  `infra/alarms.tf` (applied 2026-08-28) adds a CloudWatch Alarm on the Lambda's `Errors` metric
  → SNS topic → email, as a backstop that doesn't depend on `sendFailureAlert()`/`main.py`'s own
  `try/except` ever running (e.g. an import-time crash). SNS email subscriptions require clicking
  a confirmation link AWS sends on subscribe; the subscription stays `PendingConfirmation` (and
  silently won't deliver) until that's done. Check the inbox for `var.my_email` and confirm.

- [ ] **(2026-08-27) Confirm the deployed Lambda completes the whole pipeline end to end, then
  check a real EventBridge-triggered run too** — no real `aws lambda invoke` has actually
  finished the full pipeline yet; each one so far has surfaced one more bug and gotten one step
  further (Gmail → Claude → TTS all confirmed working individually, but the furthest any single
  invoke has reached is TTS output, before `TTS_OUTPUT_PATH` was fixed — see
  `docs/ISSUES-ENCOUNTERED.md`). That fix, plus a separate fix for the `deploy` job's Docker build
  (johnvansickle.com blocking GitHub Actions runner IPs — switched to BtbN/FFmpeg-Builds), just
  pushed (`152fb44`); next steps: (1) confirm this `deploy` run succeeds, (2) do one more manual
  invoke to confirm real SMTP delivery with the actual MP3 attachment, (3) once that's confirmed,
  check CloudWatch logs after the next scheduled Mon–Fri run to make sure a real
  EventBridge-triggered invocation goes cleanly too. Then this item can come out.

- [ ] **(2026-08-28) Confirm the deployed Lambda can label messages with the new token** — the
  re-authed `gmail.modify` token has been pushed to the SSM `GMAIL_TOKEN_JSON` parameter
  (`aws ssm put-parameter ... --overwrite`, done 2026-08-28), and labeling is confirmed working
  end to end locally (see `CLAUDE.md` Progress). Still needed: the labeling *code* itself
  (`gmail_client.py`'s `markEmailsAsProcessed()` etc.) isn't deployed yet — it needs to ship via
  the `deploy` CI job first (see the item above). Once that's out, do one manual `aws lambda
  invoke` to confirm the Lambda labels messages successfully too, then this item can come out.
  Note: on Windows Git Bash, a leading-slash SSM parameter name gets mangled by MSYS path
  conversion ("Parameter name must be a fully qualified name") — prefix the command with
  `MSYS_NO_PATHCONV=1` to avoid that.

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
