# Scope — Tech Briefing Pipeline

Snapshot of intended scope, updated in place when a real scoping decision changes it — not a
log. If the code has quietly grown past what's written here, that's drift worth a conversation,
not a reason to silently rewrite this file to match.

## What this is

A personal automation pipeline that, on a weekday (Mon–Fri) schedule:
1. Reads a fixed, pre-configured list of newsletter senders from one Gmail inbox (read-only)
2. Summarizes their recent emails into a spoken-style briefing script using Claude
3. Converts that script to an MP3 via piper-tts
4. Emails the MP3 to a small, fixed recipient list

The AWS/Terraform/GitHub Actions work exists to make this *existing* pipeline run unattended
and reproducibly on a schedule — it is infrastructure for the pipeline, not a expansion of what
the pipeline does.

## What this isn't

- **Not multi-tenant** — one Gmail inbox, one `.env` config, run for the owner's own use (and
  whoever is named in the recipient list)
- **Not real-time** — batch, scheduled cadence by design; nothing here needs to react instantly
- **Not a general newsletter/RSS aggregator** — senders are explicitly configured
  (`NEWSLETTER_SENDERS`), never auto-discovered or crawled
- **Not a web UI or dashboard** — configuration lives in `.env`, the only output artifact is an
  emailed MP3
- **Not multi-region or autoscaled** — one invocation a week comfortably fits a single Lambda
  in a single AWS region; there's no scale problem to design around

## Deployment scope

Single AWS account, single Lambda function (container image), single EventBridge Scheduler
rule. If a future ask needs more than this (e.g. multiple briefing configs, multiple
recipients lists with different schedules), that's a new scoping conversation, not an
assumption to build in now.
