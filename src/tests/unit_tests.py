"""
Unit tests — pure logic, no external API calls or file I/O.
Run with: python -m pytest src/tests/unit_tests.py -v
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.gmail_client import (
    buildSearchQuery,
    extractPlainText,
    getOrCreateProcessedLabel,
    markMessageProcessed,
    markEmailsAsProcessed,
)
from src.summarizer import formatEmailsForPrompt
from src.tts import convertToMp3, _validateSpeed
from src.mailer import _buildSubject, _buildMessage, sendBriefing
from src.config import persistGmailToken


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
# getOrCreateProcessedLabel / markMessageProcessed / markEmailsAsProcessed
# ---------------------------------------------------------------------------

class _FakeLabelsResource:
    """Minimal stand-in for service.users().labels() -- tracks create() calls."""

    def __init__(self, existingLabels):
        self._existingLabels = existingLabels
        self.createCalls = []

    def list(self, userId):
        return _FakeExecutable({"labels": self._existingLabels})

    def create(self, userId, body):
        self.createCalls.append(body)
        return _FakeExecutable({"id": "NEWLABEL123", "name": body["name"]})


class _FakeMessagesResource:
    """Minimal stand-in for service.users().messages() -- tracks modify() calls."""

    def __init__(self):
        self.modifyCalls = []

    def modify(self, userId, id, body):
        self.modifyCalls.append({"id": id, "body": body})
        return _FakeExecutable({})


class _FakeExecutable:
    """Mimics the googleapiclient pattern of chaining .execute() on every call."""

    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class _FakeUsersResource:
    def __init__(self, labelsResource, messagesResource):
        self._labels = labelsResource
        self._messages = messagesResource

    def labels(self):
        return self._labels

    def messages(self):
        return self._messages


class _FakeService:
    def __init__(self, existingLabels=None):
        self._labels = _FakeLabelsResource(existingLabels or [])
        self._messages = _FakeMessagesResource()

    def users(self):
        return _FakeUsersResource(self._labels, self._messages)


class TestGetOrCreateProcessedLabel:

    def test_labelAlreadyExists_returnsExistingId(self):
        service = _FakeService(existingLabels=[{"id": "EXISTING1", "name": "tech-briefing/processed"}])
        labelId = getOrCreateProcessedLabel(service)
        assert labelId == "EXISTING1"
        assert service._labels.createCalls == []  # never created -- already existed

    def test_labelMissing_createsAndReturnsNewId(self):
        service = _FakeService(existingLabels=[{"id": "OTHER", "name": "some-other-label"}])
        labelId = getOrCreateProcessedLabel(service)
        assert labelId == "NEWLABEL123"
        assert len(service._labels.createCalls) == 1
        assert service._labels.createCalls[0]["name"] == "tech-briefing/processed"


class TestMarkMessageProcessed:

    def test_validArgs_callsModifyWithLabelId(self):
        service = _FakeService()
        markMessageProcessed(service, "MSG123", "LABEL456")
        assert len(service._messages.modifyCalls) == 1
        call = service._messages.modifyCalls[0]
        assert call["id"] == "MSG123"
        assert call["body"]["addLabelIds"] == ["LABEL456"]

    def test_emptyMessageId_raisesValueError(self):
        with pytest.raises(ValueError):
            markMessageProcessed(_FakeService(), "", "LABEL456")

    def test_emptyLabelId_raisesValueError(self):
        with pytest.raises(ValueError):
            markMessageProcessed(_FakeService(), "MSG123", "")


class TestMarkEmailsAsProcessed:

    def test_emptyList_raisesValueError(self):
        with pytest.raises(ValueError):
            markEmailsAsProcessed([])

    def test_validEmails_labelsEachOne(self, monkeypatch):
        import src.gmail_client as gmail_client_module

        service = _FakeService(existingLabels=[{"id": "L1", "name": "tech-briefing/processed"}])
        monkeypatch.setattr(gmail_client_module, "buildGmailService", lambda: service)

        emails = [{"id": "MSG1"}, {"id": "MSG2"}]
        markEmailsAsProcessed(emails)

        assert len(service._messages.modifyCalls) == 2
        labeledIds = {call["id"] for call in service._messages.modifyCalls}
        assert labeledIds == {"MSG1", "MSG2"}


# ---------------------------------------------------------------------------
# extractPlainText
# ---------------------------------------------------------------------------

PLAIN_TEXT_PAYLOAD = {
    "mimeType": "text/plain",
    "body": {
        # base64url of "Hello, newsletter!"
        "data": "SGVsbG8sIG5ld3NsZXR0ZXIh"
    }
}

MULTIPART_PAYLOAD = {
    "mimeType": "multipart/alternative",
    "parts": [
        {
            "mimeType": "text/plain",
            "body": {"data": "SGVsbG8sIG5ld3NsZXR0ZXIh"}  # "Hello, newsletter!"
        },
        {
            "mimeType": "text/html",
            "body": {"data": "PGI+SGVsbG88L2I+"}  # "<b>Hello</b>"
        }
    ]
}

class TestExtractPlainText:

    def test_singlePartPlainText_returnsDecodedText(self):
        result = extractPlainText(PLAIN_TEXT_PAYLOAD)
        assert result == "Hello, newsletter!"

    def test_multipartAlternative_returnsPlainTextPart(self):
        result = extractPlainText(MULTIPART_PAYLOAD)
        assert result == "Hello, newsletter!"

    def test_emptyPayload_returnsEmptyString(self):
        result = extractPlainText({})
        assert result == ""

    def test_noBodyData_returnsEmptyString(self):
        payload = {"mimeType": "text/plain", "body": {}}
        result = extractPlainText(payload)
        assert result == ""

    def test_unknownMimeType_returnsEmptyString(self):
        payload = {"mimeType": "application/pdf", "body": {"data": "abc"}}
        result = extractPlainText(payload)
        assert result == ""


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


# ---------------------------------------------------------------------------
# persistGmailToken -- local-write path always; SSM write-back only when IS_LAMBDA
# ---------------------------------------------------------------------------

class TestPersistGmailToken:

    def test_emptyString_raisesValueError(self):
        with pytest.raises(ValueError):
            persistGmailToken("")

    def test_whitespaceOnly_raisesValueError(self):
        with pytest.raises(ValueError):
            persistGmailToken("   \n  ")

    def test_notLambda_writesLocalFileOnly(self, tmp_path, monkeypatch):
        import src.config as config_module

        fakeTokenPath = tmp_path / "token.json"
        monkeypatch.setattr(config_module, "TOKEN_PATH", str(fakeTokenPath))
        monkeypatch.setattr(config_module, "IS_LAMBDA", False)

        # boto3.client should never be constructed on the local-only path -- if it
        # were, this raises instead of silently succeeding against real AWS.
        def _shouldNotBeCalled(*args, **kwargs):
            raise AssertionError("boto3.client() should not be called when IS_LAMBDA is False")
        monkeypatch.setattr(config_module.boto3, "client", _shouldNotBeCalled)

        persistGmailToken('{"refresh_token": "abc"}')
        assert fakeTokenPath.read_text() == '{"refresh_token": "abc"}'

    def test_isLambda_alsoWritesBackToSsm(self, tmp_path, monkeypatch):
        import src.config as config_module

        fakeTokenPath = tmp_path / "token.json"
        monkeypatch.setattr(config_module, "TOKEN_PATH", str(fakeTokenPath))
        monkeypatch.setattr(config_module, "IS_LAMBDA", True)
        monkeypatch.setattr(config_module, "SSM_PARAMETER_PREFIX", "/daily-tech-brief")

        putCalls = []
        class _FakeSsmClient:
            def put_parameter(self, **kwargs):
                putCalls.append(kwargs)
        monkeypatch.setattr(config_module.boto3, "client", lambda service: _FakeSsmClient())

        persistGmailToken('{"refresh_token": "xyz"}')

        assert fakeTokenPath.read_text() == '{"refresh_token": "xyz"}'
        assert len(putCalls) == 1
        assert putCalls[0]["Name"] == "/daily-tech-brief/GMAIL_TOKEN_JSON"
        assert putCalls[0]["Value"] == '{"refresh_token": "xyz"}'
