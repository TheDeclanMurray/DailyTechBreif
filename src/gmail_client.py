"""
Gmail API client -- authenticates and fetches newsletter emails.
Handles token refresh automatically once token.json exists.
"""

import os
import sys
import base64
import datetime
import logging

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.config import (
    CREDENTIALS_PATH,
    TOKEN_PATH,
    GMAIL_SCOPES,
    NEWSLETTER_SENDERS,
    LOOKBACK_DAYS,
    PROCESSED_LABEL_NAME,
    persistGmailToken,
)

log = logging.getLogger("tech_briefing")

# Max emails to fetch per sender to avoid huge API payloads
MAX_RESULTS_PER_SENDER = 5


def buildGmailService():
    """
    Builds and returns an authenticated Gmail API service object.
    Refreshes the token automatically if expired.
    @returns googleapiclient.discovery.Resource -- authenticated Gmail service
    @throws SystemExit if token.json is missing (user must run auth.py first)
    @throws SystemExit if credentials cannot be refreshed
    """
    if not os.path.exists(TOKEN_PATH):
        log.error(
            "token.json not found at '%s'. "
            "Run the auth flow first:  docker compose run --rm --service-ports auth", TOKEN_PATH
        )
        sys.exit(1)

    creds = Credentials.from_authorized_user_file(TOKEN_PATH, GMAIL_SCOPES)

    # Refresh expired token using the stored refresh_token
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            log.info("Access token expired -- refreshing...")
            try:
                creds.refresh(Request())
                # Also writes back to SSM when running in Lambda -- see
                # persistGmailToken()'s docstring for why that matters.
                persistGmailToken(creds.to_json())
                log.info("Token refreshed and saved.")
            except Exception as e:
                log.error("Token refresh failed: %s. Delete token.json and re-run auth.", e)
                sys.exit(1)
        else:
            log.error("Credentials are invalid and cannot be refreshed. Re-run auth.")
            sys.exit(1)

    return build("gmail", "v1", credentials=creds)


def buildSearchQuery(senderEmail):
    """
    Constructs a Gmail search query for a specific sender within LOOKBACK_DAYS.
    Excludes messages already tagged with PROCESSED_LABEL_NAME, so a message summarized
    on a previous run doesn't get re-fetched and re-summarized on the next one.
    @param senderEmail (str) - sender address to filter on
    @returns (str) Gmail query string
    @throws ValueError if senderEmail is not a valid address
    """
    if not senderEmail or "@" not in senderEmail:
        raise ValueError(f"senderEmail must be a valid email address, got: '{senderEmail}'")

    cutoffDate = datetime.date.today() - datetime.timedelta(days=LOOKBACK_DAYS)
    dateStr = cutoffDate.strftime("%Y/%m/%d")
    # Gmail's search syntax quotes a label name containing a "/" and negates it with "-".
    return f"from:{senderEmail} after:{dateStr} -label:\"{PROCESSED_LABEL_NAME}\""


def getOrCreateProcessedLabel(service):
    """
    Finds the Gmail label id for PROCESSED_LABEL_NAME, creating the label if it doesn't
    exist yet. Gmail labels are per-account, so this only actually creates something on
    the very first run after upgrading to gmail.modify.
    @param service (googleapiclient.discovery.Resource) - authenticated Gmail service
    @returns (str) the label's id, for use in messages().modify()'s addLabelIds
    @throws HttpError if the Gmail API list/create call fails
    """
    existing = service.users().labels().list(userId="me").execute().get("labels", [])
    match = next((l for l in existing if l["name"] == PROCESSED_LABEL_NAME), None)
    if match:
        return match["id"]

    # First run since the scope upgrade -- label doesn't exist yet, create it.
    # labelListVisibility/messageListVisibility "show" keeps it visible in the Gmail UI
    # sidebar/inbox rather than hidden, so it's inspectable if something looks wrong.
    log.info("Gmail label '%s' not found -- creating it.", PROCESSED_LABEL_NAME)
    created = service.users().labels().create(
        userId="me",
        body={
            "name": PROCESSED_LABEL_NAME,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        },
    ).execute()
    return created["id"]


def markMessageProcessed(service, messageId, labelId):
    """
    Applies the processed label to a single message so future queries skip it.
    @param service (googleapiclient.discovery.Resource) - authenticated Gmail service
    @param messageId (str) - Gmail message id to label
    @param labelId (str) - label id from getOrCreateProcessedLabel()
    @returns None
    @throws ValueError if messageId or labelId is empty
    """
    if not messageId:
        raise ValueError("messageId must be a non-empty string")
    if not labelId:
        raise ValueError("labelId must be a non-empty string")

    service.users().messages().modify(
        userId="me", id=messageId, body={"addLabelIds": [labelId]}
    ).execute()


def extractPlainText(payload):
    """
    Extracts plain-text body from a Gmail message payload.
    Handles both single-part and multipart messages.
    @param payload (dict) - message payload from Gmail API response
    @returns (str) decoded plain-text body, or empty string if none found
    """
    mimeType = payload.get("mimeType", "")

    # Single-part plain text
    if mimeType == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        return ""

    # Multipart -- recurse into parts, prefer text/plain over text/html
    if mimeType.startswith("multipart"):
        parts = payload.get("parts", [])
        plainPart = next((p for p in parts if p.get("mimeType") == "text/plain"), None)
        if plainPart:
            return extractPlainText(plainPart)
        for part in parts:
            text = extractPlainText(part)
            if text:
                return text

    return ""


def fetchNewsletterEmails():
    """
    Fetches newsletter emails from Gmail for all configured senders.
    @returns (list[dict]) list of dicts with keys: sender, subject, date, body
    @throws SystemExit on fatal Gmail API errors
    """
    if not NEWSLETTER_SENDERS:
        log.error("NEWSLETTER_SENDERS is empty. Set it in .env (comma-separated email addresses).")
        sys.exit(1)

    service = buildGmailService()
    allEmails = []

    for sender in NEWSLETTER_SENDERS:
        query = buildSearchQuery(sender)
        log.info("Searching for emails from '%s' (last %d days)...", sender, LOOKBACK_DAYS)

        try:
            response = (
                service.users()
                .messages()
                .list(userId="me", q=query, maxResults=MAX_RESULTS_PER_SENDER)
                .execute()
            )
        except HttpError as e:
            log.error("Gmail API list failed for sender '%s': %s -- skipping.", sender, e)
            continue

        messages = response.get("messages", [])
        log.info("Found %d message(s) from '%s'.", len(messages), sender)

        for msg in messages:
            try:
                full = (
                    service.users()
                    .messages()
                    .get(userId="me", id=msg["id"], format="full")
                    .execute()
                )
            except HttpError as e:
                log.warning("Could not fetch message id=%s: %s -- skipping.", msg["id"], e)
                continue

            headers = {h["name"]: h["value"] for h in full.get("payload", {}).get("headers", [])}
            subject = headers.get("Subject", "(no subject)")
            date    = headers.get("Date", "(unknown date)")
            body    = extractPlainText(full.get("payload", {}))

            if not body:
                log.warning("No plain-text body for '%s' -- skipping.", subject)
                continue

            allEmails.append({
                "id":      msg["id"],
                "sender":  sender,
                "subject": subject,
                "date":    date,
                "body":    body,
            })

    log.info("Total emails fetched: %d", len(allEmails))
    return allEmails


def markEmailsAsProcessed(emails):
    """
    Labels each of the given emails as processed in Gmail, so buildSearchQuery()
    excludes them on the next run. Deliberately called only AFTER a briefing has been
    successfully delivered (see main.py) -- labeling at fetch time instead would mark an
    email as handled even if summarization or delivery failed later, permanently losing
    it from future runs.
    @param emails (list[dict]) - email dicts as returned by fetchNewsletterEmails(),
        each must have an "id" key (the Gmail message id)
    @returns None
    @throws ValueError if emails is empty
    """
    if not emails:
        raise ValueError("emails must be a non-empty list")

    service = buildGmailService()
    labelId = getOrCreateProcessedLabel(service)

    for email in emails:
        try:
            markMessageProcessed(service, email["id"], labelId)
        except HttpError as e:
            # Non-fatal -- worst case this one email gets re-summarized next run,
            # which is the same behavior as before this feature existed.
            log.warning("Could not label message id=%s as processed: %s", email["id"], e)

    log.info("Marked %d email(s) as processed.", len(emails))
