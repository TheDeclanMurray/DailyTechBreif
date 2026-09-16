"""
Unit tests — pure logic, no external API calls or file I/O.
Run with: python -m pytest src/tests/unit_tests.py -v
"""

import pytest
import sys
import os
import email
import imaplib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.gmail_client import (
    buildSearchQuery,
    extractPlainText,
    decodeMimeHeader,
    findAllMailFolder,
    findUidByMessageId,
    markMessageProcessed,
    markEmailsAsProcessed,
    _parseGmailMessageId,
)
from src.summarizer import formatEmailsForPrompt
from src.tts import convertToMp3, _validateSpeed
from src.mailer import _buildSubject, _buildMessage, sendBriefing


# ---------------------------------------------------------------------------
# buildSearchQuery
# ---------------------------------------------------------------------------

class TestBuildSearchQuery:

    def test_validSender_returnsQueryWithSenderAndDate(self):
        query = buildSearchQuery("test@example.com")
        assert "from:test@example.com" in query
        assert "after:" in query

    def test_validSender_dateFormatIsCorrect(self):
        query = buildSearchQuery("news@tldr.tech")
        # after:YYYY/MM/DD
        import re
        assert re.search(r"after:\d{4}/\d{2}/\d{2}", query)

    def test_emptySender_raisesValueError(self):
        with pytest.raises(ValueError):
            buildSearchQuery("")

    def test_noAtSign_raisesValueError(self):
        with pytest.raises(ValueError):
            buildSearchQuery("notanemail")

    def test_noneSender_raisesValueError(self):
        with pytest.raises((ValueError, AttributeError)):
            buildSearchQuery(None)

    def test_validSender_excludesProcessedLabel(self):
        # Query must exclude already-labeled messages so they aren't re-summarized.
        query = buildSearchQuery("test@example.com")
        assert '-label:"tech-briefing/processed"' in query


# ---------------------------------------------------------------------------
# IMAP helpers: findAllMailFolder / _parseGmailMessageId / findUidByMessageId /
# markMessageProcessed / markEmailsAsProcessed
# ---------------------------------------------------------------------------

class _FakeImapConnection:
    """
    Minimal stand-in for imaplib.IMAP4_SSL -- records every uid() command issued so a
    test can assert on what was sent, and replays canned responses.
    """

    def __init__(self, searchUids=None, listResponse=None, storeStatus="OK"):
        # uid("SEARCH", ...) results, as Gmail returns them: a single space-joined blob.
        self._searchUids = searchUids if searchUids is not None else [b"11 12"]
        self._listResponse = listResponse
        self._storeStatus = storeStatus
        self.uidCalls = []
        self.createCalls = []
        self.closed = False
        self.loggedOut = False

    def uid(self, command, *args):
        self.uidCalls.append((command, args))
        if command == "SEARCH":
            if not self._searchUids:
                return "OK", [b""]
            return "OK", self._searchUids
        if command == "STORE":
            return self._storeStatus, [b""]
        return "OK", [b""]

    def create(self, name):
        self.createCalls.append(name)
        return "OK", [b"created"]

    def list(self):
        if self._listResponse is None:
            return "NO", []
        return "OK", self._listResponse

    def close(self):
        self.closed = True

    def logout(self):
        self.loggedOut = True


class TestFindAllMailFolder:

    def test_allFlagPresent_returnsThatMailbox(self):
        conn = _FakeImapConnection(listResponse=[
            b'(\\HasNoChildren \\Inbox) "/" "INBOX"',
            b'(\\HasNoChildren \\All) "/" "[Gmail]/All Mail"',
        ])
        assert findAllMailFolder(conn) == "[Gmail]/All Mail"

    def test_localisedName_stillFoundByFlag(self):
        # The display name is translated but the \All special-use flag is not -- this is
        # the whole reason we match on the flag rather than the literal English name.
        conn = _FakeImapConnection(listResponse=[
            b'(\\HasNoChildren \\All) "/" "[Gmail]/Tous les messages"',
        ])
        assert findAllMailFolder(conn) == "[Gmail]/Tous les messages"

    def test_noAllFlag_fallsBackToDefault(self):
        conn = _FakeImapConnection(listResponse=[b'(\\HasNoChildren) "/" "INBOX"'])
        assert findAllMailFolder(conn) == "[Gmail]/All Mail"

    def test_listFails_fallsBackToDefault(self):
        conn = _FakeImapConnection(listResponse=None)  # LIST returns NO
        assert findAllMailFolder(conn) == "[Gmail]/All Mail"


class TestParseGmailMessageId:

    def test_typicalFetchMetadata_returnsMsgId(self):
        metadata = "12 (X-GM-MSGID 1794513002934 BODY[] {84321}"
        assert _parseGmailMessageId(metadata) == "1794513002934"

    def test_stopsBeforeTrailingByteCount(self):
        # The {84321} byte count later in the line must not be appended to the msgid.
        metadata = "7 (X-GM-MSGID 42 BODY[] {999}"
        assert _parseGmailMessageId(metadata) == "42"

    def test_markerAbsent_returnsNone(self):
        assert _parseGmailMessageId("12 (BODY[] {84321}") is None

    def test_emptyMetadata_returnsNone(self):
        assert _parseGmailMessageId("") is None


class TestFindUidByMessageId:

    def test_messageFound_returnsFirstUid(self):
        conn = _FakeImapConnection(searchUids=[b"57"])
        assert findUidByMessageId(conn, "1794513002934") == "57"
        command, args = conn.uidCalls[0]
        assert command == "SEARCH"
        assert args == ("X-GM-MSGID", "1794513002934")

    def test_noMatch_returnsNone(self):
        conn = _FakeImapConnection(searchUids=[])
        assert findUidByMessageId(conn, "1794513002934") is None

    def test_emptyMessageId_raisesValueError(self):
        with pytest.raises(ValueError):
            findUidByMessageId(_FakeImapConnection(), "")


class TestMarkMessageProcessed:

    def test_validArgs_storesGmailLabel(self):
        conn = _FakeImapConnection()
        markMessageProcessed(conn, "57")
        command, args = conn.uidCalls[0]
        assert command == "STORE"
        assert args[0] == "57"
        assert args[1] == "+X-GM-LABELS"
        assert "tech-briefing/processed" in args[2]

    def test_emptyUid_raisesValueError(self):
        with pytest.raises(ValueError):
            markMessageProcessed(_FakeImapConnection(), "")

    def test_storeRejected_raisesImapError(self):
        conn = _FakeImapConnection(storeStatus="NO")
        with pytest.raises(imaplib.IMAP4.error):
            markMessageProcessed(conn, "57")


class TestMarkEmailsAsProcessed:

    def test_emptyList_raisesValueError(self):
        with pytest.raises(ValueError):
            markEmailsAsProcessed([])

    def test_validEmails_labelsEachOne(self, monkeypatch):
        import src.gmail_client as gmail_client_module

        conn = _FakeImapConnection(searchUids=[b"57"])
        monkeypatch.setattr(gmail_client_module, "buildImapConnection", lambda: conn)

        markEmailsAsProcessed([{"id": "MSG1"}, {"id": "MSG2"}])

        stores = [c for c in conn.uidCalls if c[0] == "STORE"]
        assert len(stores) == 2
        assert conn.createCalls == ['"tech-briefing/processed"']

    def test_unresolvableMessage_isSkippedNotFatal(self, monkeypatch):
        import src.gmail_client as gmail_client_module

        # SEARCH finds nothing, so no UID -- the run must continue rather than blow up,
        # since a failure here only means the email gets re-summarized next time.
        conn = _FakeImapConnection(searchUids=[])
        monkeypatch.setattr(gmail_client_module, "buildImapConnection", lambda: conn)

        markEmailsAsProcessed([{"id": "MSG1"}])

        assert [c for c in conn.uidCalls if c[0] == "STORE"] == []

    def test_connectionIsClosedAfterwards(self, monkeypatch):
        import src.gmail_client as gmail_client_module

        conn = _FakeImapConnection(searchUids=[b"57"])
        monkeypatch.setattr(gmail_client_module, "buildImapConnection", lambda: conn)

        markEmailsAsProcessed([{"id": "MSG1"}])

        assert conn.closed and conn.loggedOut


# ---------------------------------------------------------------------------
# decodeMimeHeader
# ---------------------------------------------------------------------------

class TestDecodeMimeHeader:

    def test_encodedWord_isDecoded(self):
        # RFC 2047 base64-encoded "Hello world"
        assert decodeMimeHeader("=?UTF-8?B?SGVsbG8gd29ybGQ=?=") == "Hello world"

    def test_plainAscii_passesThrough(self):
        assert decodeMimeHeader("Weekly Digest") == "Weekly Digest"

    def test_none_returnsEmptyString(self):
        assert decodeMimeHeader(None) == ""

    def test_emptyString_returnsEmptyString(self):
        assert decodeMimeHeader("") == ""


# ---------------------------------------------------------------------------
# extractPlainText
# ---------------------------------------------------------------------------

def _message(raw):
    """Parses a raw RFC822 string into the email.message.Message extractPlainText takes."""
    return email.message_from_string(raw)


SINGLE_PART_MESSAGE = _message(
    "Subject: Test\r\n"
    "Content-Type: text/plain; charset=utf-8\r\n"
    "\r\n"
    "Hello, newsletter!"
)

MULTIPART_MESSAGE = _message(
    "Subject: Test\r\n"
    'Content-Type: multipart/alternative; boundary="BOUND"\r\n'
    "\r\n"
    "--BOUND\r\n"
    "Content-Type: text/html; charset=utf-8\r\n"
    "\r\n"
    "<b>Hello</b>\r\n"
    "--BOUND\r\n"
    "Content-Type: text/plain; charset=utf-8\r\n"
    "\r\n"
    "Hello, newsletter!\r\n"
    "--BOUND--\r\n"
)

NESTED_MULTIPART_MESSAGE = _message(
    "Subject: Test\r\n"
    'Content-Type: multipart/mixed; boundary="OUTER"\r\n'
    "\r\n"
    "--OUTER\r\n"
    'Content-Type: multipart/alternative; boundary="INNER"\r\n'
    "\r\n"
    "--INNER\r\n"
    "Content-Type: text/plain; charset=utf-8\r\n"
    "\r\n"
    "Nested body text.\r\n"
    "--INNER--\r\n"
    "--OUTER--\r\n"
)

ATTACHMENT_ONLY_MESSAGE = _message(
    "Subject: Test\r\n"
    'Content-Type: multipart/mixed; boundary="BOUND"\r\n'
    "\r\n"
    "--BOUND\r\n"
    "Content-Type: text/plain; charset=utf-8\r\n"
    'Content-Disposition: attachment; filename="notes.txt"\r\n'
    "\r\n"
    "Attached, not the body.\r\n"
    "--BOUND--\r\n"
)


class TestExtractPlainText:

    def test_singlePartPlainText_returnsDecodedText(self):
        assert extractPlainText(SINGLE_PART_MESSAGE).strip() == "Hello, newsletter!"

    def test_multipartAlternative_prefersPlainOverHtml(self):
        assert extractPlainText(MULTIPART_MESSAGE).strip() == "Hello, newsletter!"

    def test_nestedMultipart_isWalkedNotJustTopLevel(self):
        assert extractPlainText(NESTED_MULTIPART_MESSAGE).strip() == "Nested body text."

    def test_plainTextAttachment_isNotTreatedAsBody(self):
        assert extractPlainText(ATTACHMENT_ONLY_MESSAGE) == ""

    def test_none_returnsEmptyString(self):
        assert extractPlainText(None) == ""

    def test_htmlOnly_returnsEmptyString(self):
        htmlOnly = _message(
            "Subject: Test\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<b>Hi</b>"
        )
        assert extractPlainText(htmlOnly) == ""


# ---------------------------------------------------------------------------
# formatEmailsForPrompt
# ---------------------------------------------------------------------------

SAMPLE_EMAILS = [
    {"sender": "a@example.com", "subject": "News #1", "date": "Mon, 1 Jan 2025", "body": "Body one."},
    {"sender": "b@example.com", "subject": "News #2", "date": "Tue, 2 Jan 2025", "body": "Body two."},
]

class TestFormatEmailsForPrompt:

    def test_multipleEmails_includesAllSubjects(self):
        result = formatEmailsForPrompt(SAMPLE_EMAILS)
        assert "News #1" in result
        assert "News #2" in result

    def test_multipleEmails_includesSenders(self):
        result = formatEmailsForPrompt(SAMPLE_EMAILS)
        assert "a@example.com" in result
        assert "b@example.com" in result

    def test_multipleEmails_includesBodies(self):
        result = formatEmailsForPrompt(SAMPLE_EMAILS)
        assert "Body one." in result
        assert "Body two." in result

    def test_emptyList_raisesValueError(self):
        with pytest.raises(ValueError):
            formatEmailsForPrompt([])

    def test_oversizedContent_truncatesWithMarker(self, monkeypatch):
        # Patch the limit to something tiny to test truncation logic
        import src.summarizer as summarizer_module
        monkeypatch.setattr(summarizer_module, "MAX_CONTENT_CHARS", 20)
        result = formatEmailsForPrompt(SAMPLE_EMAILS)
        assert "[... content truncated ...]" in result

    def test_singleEmail_formatsCorrectly(self):
        single = [SAMPLE_EMAILS[0]]
        result = formatEmailsForPrompt(single)
        assert "--- Email 1 ---" in result
        assert "News #1" in result


# ---------------------------------------------------------------------------
# convertToMp3 -- input validation only (no subprocess in unit tests)
# ---------------------------------------------------------------------------

class TestConvertToMp3:

    def test_emptyString_raisesValueError(self):
        with pytest.raises(ValueError):
            convertToMp3("")

    def test_whitespaceOnly_raisesValueError(self):
        with pytest.raises(ValueError):
            convertToMp3("   \n  ")


class TestValidateSpeed:

    def test_normalSpeed_passes(self):
        _validateSpeed(1.0)

    def test_onePointFive_passes(self):
        _validateSpeed(1.5)

    def test_atBoundaryMin_passes(self):
        _validateSpeed(0.5)

    def test_atBoundaryMax_passes(self):
        _validateSpeed(2.0)

    def test_tooSlow_raisesValueError(self):
        with pytest.raises(ValueError):
            _validateSpeed(0.4)

    def test_tooFast_raisesValueError(self):
        with pytest.raises(ValueError):
            _validateSpeed(2.1)

    def test_zero_raisesValueError(self):
        with pytest.raises(ValueError):
            _validateSpeed(0.0)


# ---------------------------------------------------------------------------
# mailer
# ---------------------------------------------------------------------------

class TestBuildSubject:

    def test_returnsStringContainingCobaltix(self):
        subject = _buildSubject()
        assert "Cobaltix Tech Briefing" in subject

    def test_containsCurrentYear(self):
        import datetime
        subject = _buildSubject()
        assert str(datetime.date.today().year) in subject


class TestBuildMessage:

    def test_emptyMp3Bytes_raisesValueError(self):
        with pytest.raises(ValueError):
            _buildMessage("Test Subject", "Some briefing text.", b"")

    def test_emptyBriefingText_raisesValueError(self):
        with pytest.raises(ValueError):
            sendBriefing("", b"\xff\xfb\x00")

    def test_whitespaceOnlyText_raisesValueError(self):
        with pytest.raises(ValueError):
            sendBriefing("   ", b"\xff\xfb\x00")

    def test_validMessage_containsSubjectAndRecipients(self):
        import src.mailer as mailer_module
        fakeMp3Bytes = b"\xff\xfb\x00"  # minimal valid MP3 header bytes

        # Patch recipients so the test is not dependent on .env
        original = mailer_module.RECIPIENT_EMAILS
        mailer_module.RECIPIENT_EMAILS = ["test@example.com"]
        try:
            msg = _buildMessage("Cobaltix Tech Briefing - 2 June 2026", "Hello world.", fakeMp3Bytes)
            assert msg["Subject"] == "Cobaltix Tech Briefing - 2 June 2026"
            assert "test@example.com" in msg["To"]
        finally:
            mailer_module.RECIPIENT_EMAILS = original

    def test_validMessage_attachmentPresent(self):
        import src.mailer as mailer_module
        fakeMp3Bytes = b"\xff\xfb\x00"

        original = mailer_module.RECIPIENT_EMAILS
        mailer_module.RECIPIENT_EMAILS = ["test@example.com"]
        try:
            msg = _buildMessage("Subject", "Briefing text.", fakeMp3Bytes)
            payloads = msg.get_payload()
            contentTypes = [p.get_content_type() for p in payloads]
            assert "audio/mpeg" in contentTypes
        finally:
            mailer_module.RECIPIENT_EMAILS = original
