# TODO

Active items only — this is not a history. Once something is actually done, remove it (a note
worth keeping that it happened belongs in `CLAUDE.md`'s Progress section or `docs/DECISIONS.md`,
not here). Add the date an item is opened.

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

- [ ] **(2026-09-15) Verify the IMAP rewrite against the real mailbox on Lambda** —
  `src/gmail_client.py` was rewritten from the Gmail API to IMAP + App Password, but it could
  NOT be tested locally: the office network resets TLS on port 993 (see
  `docs/ISSUES-ENCOUNTERED.md`). All 56 unit tests pass, which proves the parsing/label logic
  but says nothing about whether the real connection, search, fetch and labeling work. After
  `deploy` runs, do a manual `aws lambda invoke` and confirm in CloudWatch: login succeeds, the
  All Mail folder resolves, emails are fetched, the briefing is delivered, and
  `Marked N email(s) as processed` appears. Until that's seen, treat this as unproven — the
  2026-08-28 entry in `CLAUDE.md` is a standing reminder of how convincing a green-looking run
  can be when it never touched the new code.

- [ ] **(2026-09-15) Check why the daily failure alert emails went unnoticed** —
  `sendFailureAlert()` correctly emailed `dmurray.cobaltix@gmail.com` on every one of the seven
  failed days and none were seen. That path is the pipeline's primary alerting mechanism and it
  worked; the delivery or attention side didn't. Check spam/filters on that address, and
  consider whether alerts should go somewhere noisier than the same inbox the briefing lands in.

