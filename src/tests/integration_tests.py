"""
Integration tests — hit real external services (Gmail API, Claude API).
Requires a valid .env with credentials and a populated data/token.json.

Run with: python -m pytest src/tests/integration_tests.py -v
These are intentionally NOT run in CI — trigger manually to verify live connectivity.
"""

import pytest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ---------------------------------------------------------------------------
# Gmail connectivity
# ---------------------------------------------------------------------------

class TestGmailIntegration:

    def test_buildGmailService_returnsServiceObject(self):
        """Verifies OAuth2 credentials are valid and the Gmail API is reachable."""
        from src.gmail_client import buildGmailService
        service = buildGmailService()
        assert service is not None

    def test_fetchNewsletterEmails_returnsListWithoutCrashing(self):
        """
        Fetches emails from configured senders.
        Passes even if 0 emails found — only fails on API errors.
        """
        from src.gmail_client import fetchNewsletterEmails
        emails = fetchNewsletterEmails()
        assert isinstance(emails, list)
        for email in emails:
            assert "sender" in email
            assert "subject" in email
            assert "body" in email
            assert isinstance(email["body"], str)


# ---------------------------------------------------------------------------
# Claude API connectivity
# ---------------------------------------------------------------------------

class TestClaudeIntegration:

    MINIMAL_EMAILS = [
        {
            "sender": "test@example.com",
            "subject": "Integration test email",
            "date":    "Mon, 1 Jan 2025",
            "body":    "AWS released a new EC2 instance type. Anthropic released Claude 4.",
        }
    ]

    def test_summarizeEmails_returnsNonEmptyString(self):
        """Sends a minimal payload to Claude and verifies a response is returned."""
        from src.summarizer import summarizeEmails
        result = summarizeEmails(self.MINIMAL_EMAILS)
        assert isinstance(result, str)
        assert len(result) > 50  # A real briefing will always exceed this

    def test_summarizeEmails_emptyList_returnsEmptyString(self):
        """Empty input should return empty without hitting the API."""
        from src.summarizer import summarizeEmails
        result = summarizeEmails([])
        assert result == ""


# ---------------------------------------------------------------------------
# SMTP connectivity
# ---------------------------------------------------------------------------

class TestMailerIntegration:

    def test_sendBriefing_deliversEmail(self):
        """
        Sends a real email via SMTP. Requires valid SMTP credentials in .env.
        Check your inbox after running this -- it will actually deliver.
        """
        from src.mailer import sendBriefing

        fakeMp3Bytes = b"\xff\xfb\x00"

        sendBriefing("This is an integration test briefing from the tech-briefing pipeline.", fakeMp3Bytes)
