# Issues Encountered

Running log of problems hit during the project and how they were resolved (or the compromise
made), with the date. Append-only — entries are never edited or removed once added.

- **(2026-08-21) No git repo, and no discoverable credentials for the target GitHub repo.**
  While planning the IaC/CI-CD architecture, checked this machine for what pushing to
  `https://github.com/TheDeclanMurray/DailyTechBreif.git` would need: no `.git` directory
  exists yet in this project, no global `git user.name`/`user.email` is configured, and the
  `gh` CLI isn't installed. Nothing was pushed or force-configured — asked the user how they
  want to authenticate (e.g. `gh auth login`, an existing SSH key already registered to the
  `TheDeclanMurray` GitHub account, or a PAT via Windows Git Credential Manager) rather than
  guessing at credential handling for an outward-facing push. **Resolved 2026-08-24**: user
  confirmed they have `git` CLI credentials already working for the `TheDeclanMurray` account;
  remote added and `git push -u origin main` succeeded first try — `main` is live at
  https://github.com/TheDeclanMurray/DailyTechBreif.

- **(2026-08-24) `docker compose run --rm auth` never published port 8080, so the OAuth
  redirect always failed with "localhost refused to connect."** During a local pre-Terraform
  test run, `data/token.json` had gone stale (`invalid_grant`) and needed regenerating.
  Every reference to the auth flow in the repo — `docker-compose.yml`'s own comment,
  `README.md`, `CLAUDE.md`, `docs/GMAIL_SETUP.md`, `src/auth.py`'s docstring, and the error
  message in `src/gmail_client.py` — documented the command as plain
  `docker compose run --rm auth`. That command does not publish a service's `ports:` mapping;
  only `docker compose up` does that automatically, or `run` with `-P`/`--service-ports`
  (confirmed via `docker compose run --help`). So the container was listening on 8080
  internally, but nothing on the host forwarded the browser's redirect to it — confirmed via
  `docker ps` showing an empty `PORTS` column on the running container. The `docker-compose.yml`
  comment itself was additionally stale, describing an old paste-the-code OOB flow that
  `src/auth.py` no longer implements (it's a loopback-redirect listener now), which is likely
  how the missing flag went unnoticed for so long. **Resolved same day**: added
  `--service-ports` to all six references and corrected the stale flow description.
  Recovery for the specific stuck run: the container was still alive and blocked on its one
  `server.handle_request()` call with the correct PKCE `code_verifier` in memory, so rather
  than restart the whole browser flow, the already-issued `code` from the browser's failed
  redirect URL was replayed straight to the container's internal listener via
  `docker exec <container> wget -qO- "http://127.0.0.1:8080/?code=<urlencoded>&state=..."`,
  which completed the token exchange normally.

- **(2026-08-25) Lambda `CreateFunction` rejected the pushed image: "the image manifest, config
  or layer media type for the source image ... is not supported."** During the first
  `terraform apply` bootstrap (pushing a placeholder `:initial` image per `infra/README.md`),
  a plain `docker build` + `docker push` produced an image Lambda couldn't read. Cause: recent
  Docker Desktop versions route `docker build` through BuildKit/buildx by default, which attaches
  provenance/SBOM attestation manifests to the image — a multi-manifest format Lambda's
  `CreateFunction` doesn't parse, only a plain single-arch image manifest. **Resolved same day**:
  rebuilt and pushed with attestations disabled and the architecture pinned explicitly (Lambda
  defaults to x86_64, per `infra/lambda.tf`'s unset `architectures`):
  `docker buildx build --platform linux/amd64 --provenance=false --sbom=false -t <repo>:initial --push .`

- **(2026-08-26) Deployed Lambda has been crashing on every scheduled invocation since it went
  live, with zero alert sent.** `infra/` was applied to AWS on 2026-08-25 (Terraform, Phase 3 of
  `docs/AWS_DEPLOYMENT_PLAN.md`) before the code-side Phase 2 changes it depends on were actually
  made. Confirmed via live CloudWatch logs on 2026-08-26: every invocation (Tue 08-25 and Wed
  08-26, 3 attempts each — Lambda's automatic async retry policy) crashes identically at import
  time with `OSError: [Errno 30] Read-only file system: 'logs'`, because `src/logger.py` still
  tries to create a relative `logs/` directory and Lambda's filesystem is read-only outside
  `/tmp`. Because the crash happens before `main.py`'s `try/except` is reached,
  `sendFailureAlert()` never runs — two full days of failures produced no notification to anyone.
  **Resolved 2026-08-26**: added `src/lambda_handler.py`, switched `src/logger.py`'s `LOG_PATH`
  to `/tmp/pipeline.log` under `IS_LAMBDA`, made `src/config.py` SSM-aware, and switched the
  Dockerfile to a Lambda-compatible base (see the two build-fix entries below and
  `docs/DECISIONS.md` for the full set of changes). Verified locally via a real `docker build` +
  a live piper-to-ffmpeg synthesis run inside the built image + booting it through its actual
  Lambda CMD and confirming the Runtime Interface Client starts cleanly in `/var/task` with
  `src.lambda_handler` importable -- not yet verified against a real EventBridge-triggered
  invocation in AWS, since this fix hasn't been deployed yet (blocked on the commit/push and
  `AWS_DEPLOY_ROLE_ARN` items in `docs/TODO.md`).

- **(2026-08-26) Lambda-base Dockerfile build failed twice before succeeding, both from
  Debian-vs-Amazon-Linux-2023 package differences.** While implementing the fix above:
  1. `tar -xzf` failed with `gzip: Cannot exec: No such file or directory` -- this Lambda base
     image's minimal install doesn't include `gzip` as a separate binary the way
     `python:3.12-slim` did. **Fixed**: added `gzip` to the `dnf install` list.
  2. `ldconfig` failed with `command not found` -- used after unpacking piper's bundled `.so`
     files, again present by default on Debian but not on this minimal AL2023-based image.
     **Fixed**: dropped the `/etc/ld.so.conf.d` + `ldconfig` step entirely and set
     `LD_LIBRARY_PATH` instead, which needs no extra binary -- see `docs/DECISIONS.md`.
  Both were only caught by actually running `docker build` locally (Docker Desktop wasn't
  running at the start of this session; started specifically to de-risk this untested base-image
  swap rather than guessing at AL2023 package availability from documentation alone).

- **(2026-08-26) `deploy` job's OIDC auth step failed on every push with `AccessDenied: Not
  authorized to perform sts:AssumeRoleWithWebIdentity`, despite the trust policy looking
  correct.** After setting `AWS_DEPLOY_ROLE_ARN` (and, on the first attempt, discovering it had
  been added as a GitHub Actions **secret** rather than a **variable** — `deploy.yml` reads
  `vars.*`, so a secret-only value resolves to an empty string; same fix applied to
  `AWS_REGION`/`ECR_REPOSITORY`/`LAMBDA_FUNCTION_NAME` when they turned out to have the same
  problem), the auth step still failed. Compared the applied trust policy (`infra/iam.tf`) byte
  for byte against GitHub's actual token — repo name casing, branch, `aud`, the OIDC provider
  ARN and its `client_id_list`/`thumbprint_list`, permissions boundaries, AWS Organizations SCPs
  (none — account isn't in an org) — everything matched. Root cause only surfaced via CloudTrail
  (`aws cloudtrail lookup-events --lookup-attributes AttributeKey=EventName,AttributeValue=AssumeRoleWithWebIdentity`):
  the `userIdentity.userName` on every denied attempt was
  `repo:TheDeclanMurray@111345815/DailyTechBreif@1342264423:ref:refs/heads/main`, not the plain
  `repo:TheDeclanMurray/DailyTechBreif:ref:refs/heads/main` the trust policy's `StringLike`
  condition was written against. GitHub includes the numeric, immutable owner ID and repo ID in
  the `sub` claim (a security feature protecting against a renamed/transferred/recreated repo
  silently inheriting old trust) — the original trust policy just never matched it. **Resolved
  same day**: added `github_owner_id`/`github_repo_id` to `infra/variables.tf` and updated the
  `sub` condition in `infra/iam.tf` to include them, `terraform apply`'d locally, confirmed via
  `aws iam get-role` that the deployed trust policy now matches CloudTrail's observed subject
  exactly.

- **(2026-08-26) All three SSM secrets were still the Terraform-applied `REPLACE_ME` placeholder
  -- never actually seeded despite CLAUDE.md's Progress section claiming they were (2026-08-25
  entry).** Discovered via a manual `aws lambda invoke`: Gmail auth failed with
  `JSONDecodeError` loading the token, and separately the failure-alert email itself failed with
  SMTP `535 Username and Password not accepted`. User confirmed the SSM values had genuinely
  never been set. **Resolved same day**: user set all three (`ANTHROPIC_API_KEY`,
  `SMTP_PASSWORD`, `GMAIL_TOKEN_JSON`) via the AWS Console UI, reusing the same values already
  working locally in `.env`/`data/token.json` -- a CLI attempt (`aws ssm put-parameter --name
  /daily-tech-brief/...`) hit `ValidationException: Parameter name must be a fully qualified
  name` first, almost certainly Git Bash's MSYS auto-converting the leading `/` into a Windows
  path (the same class of issue as the `--entrypoint /usr/local/bin/piper` case above);
  `MSYS_NO_PATHCONV=1` would likely fix it if the CLI route is wanted later, but the Console UI
  sidestepped it entirely.

- **(2026-08-26) `ffmpeg not found at '/usr/bin/ffmpeg'` on the first real Lambda invocation
  after the secrets were fixed.** Gmail fetch, SSM secrets, and Claude summarization all
  succeeded (confirmed via a real generated briefing script in the logs) -- pipeline died at the
  TTS step. `src/tts.py`'s `FFMPEG_BINARY` constant was never updated when the Dockerfile moved
  from `python:3.12-slim` (where `apt-get install ffmpeg` puts it at `/usr/bin/ffmpeg`) to the
  Lambda base image's static ffmpeg build (installed to `/usr/local/bin/ffmpeg` -- see
  `docs/DECISIONS.md`). Missed during local Docker verification because that testing ran `ffmpeg`
  directly by its known path rather than through `src/tts.py`'s own path constant. **Resolved
  same day**: updated `FFMPEG_BINARY` to `/usr/local/bin/ffmpeg`, verified inside a rebuilt image
  that both `PIPER_BINARY` and `FFMPEG_BINARY` resolve via `os.path.exists()` before pushing.

- **(2026-08-26) `OSError: Read-only file system: 'data'` on the next real Lambda invoke, after
  the ffmpeg fix above.** Gmail fetch, Claude summarization, and the piper/ffmpeg TTS binaries
  all resolved correctly this time -- died one line further in, at
  `os.makedirs(os.path.dirname(TTS_OUTPUT_PATH))` in `src/tts.py`. `config.py`'s
  `TTS_OUTPUT_PATH` was still a relative `data/briefing.mp3` path -- the same root cause as the
  original `logs/` crash, just a second constant missed when `LOG_PATH` and `TOKEN_PATH` were
  made Lambda-aware. Grepped for every other relative-path/`os.makedirs()` call in `src/` this
  time before concluding it was the last one. **Resolved same day**: `TTS_OUTPUT_PATH` is now
  `/tmp/briefing.mp3` under `IS_LAMBDA`, matching `LOG_PATH`'s existing pattern.
