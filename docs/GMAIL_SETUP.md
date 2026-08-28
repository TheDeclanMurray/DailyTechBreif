# Gmail API Setup — Step-by-Step

Follow these steps once to create a `credentials.json` file that gives the pipeline
access to your Gmail inbox (read messages and apply the `tech-briefing/processed` label).

---

## 1. Create a Google Cloud Project

1. Go to [https://console.cloud.google.com](https://console.cloud.google.com)
2. Click the project selector at the top → **New Project**
3. Name it something like `tech-briefing`
4. Click **Create** and wait for it to finish

---

## 2. Enable the Gmail API

1. In the left sidebar: **APIs & Services → Library**
2. Search for **Gmail API**
3. Click it → click **Enable**

---

## 3. Configure the OAuth Consent Screen

1. Go to **APIs & Services → OAuth consent screen**
2. Choose **External** (works for personal Gmail accounts) → **Create**
3. Fill in the required fields:
   - **App name**: `Tech Briefing` (or anything you like)
   - **User support email**: your Gmail address
   - **Developer contact email**: your Gmail address
4. Click **Save and Continue** through the Scopes and Test Users screens
   - On **Scopes**: click **Add or Remove Scopes** → search for `gmail.modify` →
     tick it → **Update** → **Save and Continue**. `gmail.modify` is required (not just
     `gmail.readonly`) because the pipeline applies a `tech-briefing/processed` label to
     each email once it's been summarized, to avoid re-summarizing it on the next run.
     Google shows a more sensitive-data consent warning for `modify` — that's expected.
   - On **Test Users**: click **Add Users** → add your Gmail address → **Save and Continue**
5. Click **Back to Dashboard**

> **Why External + Test Users?** For a personal pipeline you never need to publish
> the app. Keeping it in "Testing" mode is fine and avoids Google's verification process.

---

## 4. Create OAuth 2.0 Credentials

1. Go to **APIs & Services → Credentials**
2. Click **+ Create Credentials → OAuth client ID**
3. Application type: **Desktop app**
4. Name: `tech-briefing-desktop` (or anything)
5. Click **Create**
6. In the popup, click **Download JSON**
7. Rename the downloaded file to `credentials.json`
8. Place it in the `data/` folder of this project

Your `data/` folder should now contain:
```
data/
└── credentials.json   ← just downloaded
```
`token.json` will be created automatically in the next step.

---

## 5. Run the Auth Flow (generates token.json)

**Option A — Docker (recommended):**
```bash
docker compose run --rm --service-ports auth
```
`--service-ports` is required — plain `docker compose run` does not publish the `ports:`
mapping from docker-compose.yml (that only happens automatically with `up`), so without it
there's nothing on the host listening for the OAuth redirect and the browser will show
"localhost refused to connect".

A URL will be printed. Open it in your browser on the same machine. Authorise the app —
the container's local server on port 8080 catches the redirect automatically and writes
`token.json`; no code-pasting needed. (If running on a truly headless server with no
browser access at all, forward port 8080 over SSH first: `ssh -L 8080:localhost:8080 user@host`.)

**Option B — Directly on the server (no Docker):**
```bash
pip install -r requirements.txt
python -m src.auth
```

After authorising, `data/token.json` is written automatically.

---

## 6. Verify it Works

```bash
docker compose run --rm tech-briefing python -m pytest src/tests/integration_tests.py::TestGmailIntegration -v
```

You should see `test_buildGmailService_returnsServiceObject PASSED`.

---

## 7. Notes on Token Refresh

- `token.json` contains a **refresh token** that automatically renews the short-lived
  access token — you do NOT need to re-run the auth flow periodically.
- The pipeline refreshes the token silently if it finds it expired.
- If you ever see `Token refresh failed`, delete `data/token.json` and re-run Step 5.

---

## Security Reminders

- `credentials.json` and `token.json` are in `.gitignore` and `.claudeignore`.
- Never commit them. Never share them. They grant access to your Gmail inbox.
- The OAuth scope is `gmail.modify` — the pipeline can read messages and add/remove labels
  (specifically, it applies its own `tech-briefing/processed` label after summarizing an
  email). It still cannot send, delete, or read/modify emails outside the Gmail API's
  `modify` permission set.

## Upgrading an Existing Setup from `gmail.readonly` to `gmail.modify`

If you set this pipeline up before 2026-08-28, your `token.json` was issued under the old
`gmail.readonly` scope and Gmail will reject label-modifying calls against it. To upgrade:

1. Make sure your OAuth consent screen's Scopes include `gmail.modify` (Step 3 above) —
   if you only ever added `gmail.readonly`, add `gmail.modify` there now (you don't need to
   remove `gmail.readonly`, `gmail.modify` is a superset).
2. Delete the old `data/token.json`.
3. Re-run Step 5 (`docker compose run --rm --service-ports auth`) to re-consent and get a
   token with the new scope.
4. If deployed to Lambda, the SSM `GMAIL_TOKEN_JSON` parameter also needs updating with the
   new token's contents — `src/auth.py` only ever writes the local `data/token.json` file,
   it doesn't touch SSM, so push it manually:
   `aws ssm put-parameter --name "<SSM_PARAMETER_PREFIX>/GMAIL_TOKEN_JSON" --type SecureString --overwrite --value "$(cat data/token.json)"`
