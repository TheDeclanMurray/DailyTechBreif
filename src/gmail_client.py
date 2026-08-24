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
            "Run the auth flow first:  docker compose run --rm auth", TOKEN_PATH
        )
        sys.exit(1)

    creds = Credentials.from_authorized_user_file(TOKEN_PATH, GMAIL_SCOPES)

    # Refresh expired token using the stored refresh_token
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            log.info("Access token expired -- refreshing...")
            try:
                creds.refresh(Request())
                with open(TOKEN_PATH, "w") as f:
                    f.write(creds.to_json())
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
    @param senderEmail (str) - sender address to filter on
    @returns (str) Gmail query string
    @throws ValueError if senderEmail is not a valid address
    """
    if not senderEmail or "@" not in senderEmail:
        raise ValueError(f"senderEmail must be a valid email address, got: '{senderEmail}'")

    cutoffDate = datetime.date.today() - datetime.timedelta(days=LOOKBACK_DAYS)
    dateStr = cutoffDate.strftime("%Y/%m/%d")
    return f"from:{senderEmail} after:{dateStr}"


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
                "sender":  sender,
                "subject": subject,
                "date":    date,
                "body":    body,
            })

    log.info("Total emails fetched: %d", len(allEmails))
    return allEmails
