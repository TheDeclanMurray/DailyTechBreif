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
