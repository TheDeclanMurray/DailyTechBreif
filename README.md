# Tech Briefing Pipeline

Automated daily/weekly tech briefing: pulls newsletter emails from Gmail, summarises them with
Claude into a spoken-style script, converts that to an MP3 via piper-tts, and emails it out.

## Setup

1. Follow [docs/GMAIL_SETUP.md](docs/GMAIL_SETUP.md) to create Google Cloud credentials and
   download `data/credentials.json`.
2. Copy `.env.example` to `.env` and fill in your values.
3. Run the one-time OAuth flow: `docker compose run --rm auth`
4. Run the pipeline: `./run` (or `./run -b` to rebuild the image first)

## More detail

- [CLAUDE.md](CLAUDE.md) — full architecture, file/folder layout, and current progress
- [docs/](docs/) — design notes, decisions, known issues, and setup/deployment guides
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — canonical stack/hosting/IaC/CI-CD summary
- [docs/SCOPE.md](docs/SCOPE.md) — what this project is and isn't trying to do
- [docs/GMAIL_SETUP.md](docs/GMAIL_SETUP.md) — step-by-step Google Cloud Console instructions
- [docs/AWS_DEPLOYMENT_PLAN.md](docs/AWS_DEPLOYMENT_PLAN.md) — detailed Lambda + GitHub Actions migration plan
- [docs/DECISIONS.md](docs/DECISIONS.md) — running design decisions log
- [docs/ISSUES-ENCOUNTERED.md](docs/ISSUES-ENCOUNTERED.md) — running problems/resolutions log
- [infra/](infra/) — Terraform IaC (currently stubs, see infra/README.md)
