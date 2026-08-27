# Tech Briefing Pipeline

Automated weekday tech briefing: pulls newsletter emails from Gmail, summarises them with
Claude into a spoken-style script, converts that to an MP3 via piper-tts, and emails it out
on a Mon–Fri schedule.

## Setup

1. Follow [docs/GMAIL_SETUP.md](docs/GMAIL_SETUP.md) to create Google Cloud credentials and
   download `data/credentials.json`.
2. Copy `.env.example` to `.env` and fill in your values.
3. Run the one-time OAuth flow: `docker compose run --rm --service-ports auth`
   (`--service-ports` is required — plain `docker compose run` does not publish the `ports:`
   from docker-compose.yml, so the OAuth redirect to `localhost:8080` would otherwise have
   nothing listening on the host to catch it)
4. Run the pipeline: `./run` (or `./run -b` to rebuild the image first)

## Testing

Run the unit suite in its own container instead of a throwaway host venv:
`docker compose run --rm test`

This uses `Dockerfile.test` (plain `python:3.12-slim`, no piper/ffmpeg) and bind-mounts
`src/` so edits are picked up without a rebuild. `integration_tests.py` needs live
Gmail/Claude credentials and stays out of this — run it manually if needed.

## More detail

- [CLAUDE.md](CLAUDE.md) — full architecture, file/folder layout, and current progress
- [docs/](docs/) — design notes, decisions, known issues, and setup/deployment guides
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — canonical stack/hosting/IaC/CI-CD summary
- [docs/SCOPE.md](docs/SCOPE.md) — what this project is and isn't trying to do
- [docs/GMAIL_SETUP.md](docs/GMAIL_SETUP.md) — step-by-step Google Cloud Console instructions
- [docs/AWS_DEPLOYMENT_PLAN.md](docs/AWS_DEPLOYMENT_PLAN.md) — detailed Lambda + GitHub Actions migration plan
- [docs/DECISIONS.md](docs/DECISIONS.md) — running design decisions log
- [docs/ISSUES-ENCOUNTERED.md](docs/ISSUES-ENCOUNTERED.md) — running problems/resolutions log
- [infra/](infra/) — Terraform IaC for the AWS Lambda deployment (applied to AWS 2026-08-25;
  CI/CD deploy pipeline working since 2026-08-26; full end-to-end delivery from the deployed
  Lambda not yet confirmed, see `docs/TODO.md`)
