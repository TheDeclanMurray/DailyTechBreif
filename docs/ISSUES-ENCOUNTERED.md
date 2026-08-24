# Issues Encountered

Running log of problems hit during the project and how they were resolved (or the compromise
made), with the date. Append-only.

- **(2026-08-21) No git repo, and no discoverable credentials for the target GitHub repo.**
  While planning the IaC/CI-CD architecture, checked this machine for what pushing to
  `https://github.com/TheDeclanMurray/DailyTechBreif.git` would need: no `.git` directory
  exists yet in this project, no global `git user.name`/`user.email` is configured, and the
  `gh` CLI isn't installed. Nothing was pushed or force-configured — asked the user how they
  want to authenticate (e.g. `gh auth login`, an existing SSH key already registered to the
  `TheDeclanMurray` GitHub account, or a PAT via Windows Git Credential Manager) rather than
  guessing at credential handling for an outward-facing push. Resolution: pending — see the
  question raised in the same session.
