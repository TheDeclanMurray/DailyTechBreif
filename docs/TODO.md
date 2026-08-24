# TODO

Outstanding follow-ups for the Tech Briefing Pipeline. Add the date an item is opened; check it
off (with the date) once resolved, don't delete history.

- [ ] **(2026-08-21) Fix prompt caching on the system prompt** — [src/summarizer.py](../src/summarizer.py)
  sends the ~700-word `SYSTEM_PROMPT` in the `system` field with a comment claiming Claude caches
  it automatically after the first call. That's incorrect: Anthropic prompt caching only applies
  to blocks with an explicit `cache_control: {"type": "ephemeral"}` breakpoint. Right now only the
  daily email content (the user turn) is cached — the large static system prompt is paid for in
  full on every run. Fix: restructure the `system` field as a list with a `cache_control` block on
  the system prompt text, same pattern already used for the user message. Also update the
  "~90% savings" claim in `src/config.py` and `CLAUDE.md` once fixed to reflect the real number.

- [ ] **(2026-08-21) Start each run with a clean log instead of appending forever** —
  [src/logger.py](../src/logger.py) opens `logs/pipeline.log` with `FileHandler(..., mode="a")`,
  so the file grows without bound across every run. Not urgent on the deployed cron target (one
  run a week), but locally — running the pipeline repeatedly during development — it balloons
  fast. Fix: truncate the log at the start of each run (`mode="w"`, or an explicit
  `open(LOG_PATH, "w").close()` before attaching the handler) so every run starts clean. If any
  history across runs is still wanted, consider rotating to `pipeline.log.1` before truncating
  instead of just discarding it.
