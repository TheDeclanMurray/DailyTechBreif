# Gmail Setup — Step-by-Step

**Purpose:** everything needed to give the pipeline access to the Gmail account it reads
newsletters from and sends the briefing through. One credential — a Gmail **App Password** —
covers both directions: IMAP for reading, SMTP for sending.

> **This guide replaced a Google Cloud Console / OAuth2 walkthrough on 2026-09-15.** If you're
> looking for the old `credentials.json` + `token.json` + `docker compose run auth` flow, it's
> gone on purpose. See [DECISIONS.md](DECISIONS.md) for why, but the short version: `gmail.modify`
> is a Google *restricted* scope, so an unverified External app had to stay in "Testing" mode,
> where Google **expires the refresh token after exactly 7 days**. That silently killed seven
> consecutive days of briefings (2026-09-07 → 2026-09-15). App Passwords don't expire.

---

## 1. Turn on 2-Step Verification

App Passwords only exist on accounts with 2-Step Verification enabled — the option is hidden
otherwise.

1. Go to [myaccount.google.com/security](https://myaccount.google.com/security)
2. Under **How you sign in to Google**, click **2-Step Verification**
3. Follow the prompts if it isn't already on

---

## 2. Create an App Password

1. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
2. Enter a name you'll recognise later, e.g. `tech-briefing`
3. Click **Create**
4. Copy the 16-character password it shows you — **this is the only time it's displayed**

It looks like `abcd efgh ijkl mnop`. The spaces are cosmetic; keep them or strip them, Google
accepts both.

> **This is not your Google account password.** It's a separate credential scoped to this one
> app, revocable on its own from the same page without touching anything else.

---

## 3. Confirm IMAP is enabled

Most Gmail accounts have IMAP on by default now, but it's worth 10 seconds to check:

1. Gmail → **⚙ Settings** → **See all settings**
2. **Forwarding and POP/IMAP** tab
3. Under **IMAP access**, confirm it says **Status: IMAP is enabled**
4. If not, select **Enable IMAP** and **Save Changes**

If the tab isn't there at all, IMAP is permanently on for your account and there's nothing to do.

---

## 4. Put it in `.env`

Copy `.env.example` to `.env` if you haven't already, then fill in:

```
MY_EMAIL=you@gmail.com
SMTP_USER=you@gmail.com
SMTP_PASSWORD=abcd efgh ijkl mnop     # the App Password from step 2
```

`IMAP_USER` and `IMAP_PASSWORD` default to `SMTP_USER`/`SMTP_PASSWORD`, since it's the same
mailbox and the same credential. Only set them explicitly if you ever want reading and sending
to use different accounts.

That's the whole setup. There is no one-off auth command to run, no browser consent flow, and
nothing that expires.

---

## 5. Seed the Lambda's copy (deployed runs only)

Local runs read `.env`. Lambda has no `.env`, so it reads the same secret from SSM Parameter
Store:

```bash
aws ssm put-parameter \
  --name /daily-tech-brief/SMTP_PASSWORD \
  --type SecureString \
  --value "abcd efgh ijkl mnop" \
  --overwrite
```

Only needed once, or whenever you rotate the App Password.

---

## Troubleshooting

**`IMAP login failed ... AUTHENTICATIONFAILED`**
The App Password was revoked, mistyped, or 2-Step Verification was turned off on the account
(which invalidates every App Password at once). Generate a fresh one via step 2.

**`SSL: UNEXPECTED_EOF_WHILE_READING` or `ConnectionResetError` on port 993**
Your *network* is blocking IMAPS, not Google. Corporate networks commonly allow SMTP submission
on 587 while blocking 993 and 465 — the Cobaltix office network does exactly this, which is why
the pipeline can't be tested against real Gmail from the office. Deployed Lambda runs are
unaffected (no VPC, unrestricted AWS egress). To test locally, use a different network.

**Zero emails fetched, no error**
Either nothing arrived from `NEWSLETTER_SENDERS` inside `LOOKBACK_DAYS`, or everything matching
already carries the `tech-briefing/processed` label. Search Gmail for
`label:tech-briefing/processed` to see what's been consumed; remove the label from a message to
make it eligible again.

---

## What the pipeline touches

- **Reads** messages from the senders listed in `NEWSLETTER_SENDERS`, within `LOOKBACK_DAYS`,
  searching All Mail (so archived newsletters still count).
- **Applies** the `tech-briefing/processed` label to messages it has successfully summarised and
  delivered, so the next run skips them. Fetching uses `BODY.PEEK[]`, so reading a newsletter
  does not mark it as read.
- **Sends** the briefing email via SMTP from the same account.

It never deletes anything, and never modifies message content.
