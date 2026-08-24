"""
Email delivery -- sends the daily briefing MP3 and plain-text script via SMTP.
Also provides sendFailureAlert() for notifying the developer when the pipeline fails.
Uses Python's stdlib smtplib and email modules, no extra dependencies required.
Authenticates with STARTTLS on port 587 using a Gmail App Password.
"""

import os
import sys
import logging
import smtplib
import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.audio import MIMEAudio

from src.config import (
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USER,
    SMTP_PASSWORD,
    RECIPIENT_EMAILS,
    DEVELOPER_EMAIL,
)

log = logging.getLogger("tech_briefing")


def _validateConfig():
    """
    Checks that all required SMTP config values are present.
    @throws SystemExit if any value is missing
    """
    missing = []
    if not SMTP_USER:
        missing.append("SMTP_USER")
    if not SMTP_PASSWORD:
        missing.append("SMTP_PASSWORD")
    if not RECIPIENT_EMAILS:
        missing.append("RECIPIENT_EMAILS")

    if missing:
        log.error("Missing required .env values: %s", ", ".join(missing))
        sys.exit(1)


def _buildSubject():
    """
    Builds the briefing email subject line with today's date.
    @returns (str) subject string e.g. "Cobaltix Tech Briefing - 2 June 2026"
    """
    today = datetime.date.today()
    dateStr = f"{today.day} {today.strftime('%B %Y')}"
    return f"Cobaltix Tech Briefing - {dateStr}"


def _buildMessage(subject, briefingText, mp3Path):
    """
    Constructs a multipart email with the briefing as the body and MP3 as attachment.
    @param subject (str) - email subject line
    @param briefingText (str) - plain-prose briefing script for the email body
    @param mp3Path (str) - path to the MP3 file to attach
    @returns MIMEMultipart - fully constructed email message object
    @throws FileNotFoundError if mp3Path does not exist
    """
    if not os.path.exists(mp3Path):
        raise FileNotFoundError(f"MP3 file not found at '{mp3Path}' -- run TTS step first.")

    msg = MIMEMultipart()
    msg["From"]    = SMTP_USER
    msg["To"]      = ", ".join(RECIPIENT_EMAILS)
    msg["Subject"] = subject

    # Plain-text body -- same prose script sent to TTS, useful for reference
    # and for copying sections into Claude for follow-up questions
    bodyText = (
        "Your daily tech briefing is attached as an MP3.\n\n"
        "The full written script is below if you want to read along, "
        "search for something, or copy a section into Claude for more detail.\n\n"
        "---\n\n"
        + briefingText
    )
    msg.attach(MIMEText(bodyText, "plain"))

    # MP3 attachment
    with open(mp3Path, "rb") as mp3File:
        audio = MIMEAudio(mp3File.read(), _subtype="mpeg")

    mp3Filename = os.path.basename(mp3Path)
    audio.add_header("Content-Disposition", "attachment", filename=mp3Filename)
    msg.attach(audio)

    return msg


def _smtpSend(toAddresses, msg):
    """
    Opens an SMTP connection and sends a pre-built message.
    Shared by sendBriefing() and sendFailureAlert() to avoid duplication.
    @param toAddresses (list[str]) - recipient addresses, must be non-empty
    @param msg (MIMEMultipart) - fully built message object
    @throws smtplib.SMTPAuthenticationError on bad credentials
    @throws smtplib.SMTPException on other SMTP errors
    @throws OSError on connection failure
    """
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, toAddresses, msg.as_string())


def sendBriefing(briefingText, mp3Path):
    """
    Sends the daily briefing email to all configured recipients.
    @param briefingText (str) - plain-prose briefing script, must be non-empty
    @param mp3Path (str) - path to the MP3 attachment, must exist
    @returns None
    @throws ValueError if briefingText is empty
    @throws SystemExit on SMTP authentication failure or connection error
    """
    if not briefingText or not briefingText.strip():
        raise ValueError("briefingText must not be empty")

    _validateConfig()

    subject = _buildSubject()
    msg = _buildMessage(subject, briefingText, mp3Path)

    log.info("Sending '%s' to %d recipient(s)...", subject, len(RECIPIENT_EMAILS))

    try:
        _smtpSend(RECIPIENT_EMAILS, msg)
    except smtplib.SMTPAuthenticationError:
        log.error(
            "SMTP authentication failed. Check SMTP_USER and SMTP_PASSWORD in .env. "
            "Gmail requires an App Password -- your account password will not work."
        )
        sys.exit(1)
    except smtplib.SMTPException as e:
        log.error("SMTP error while sending briefing: %s", e)
        sys.exit(1)
    except OSError as e:
        log.error("Could not connect to %s:%d -- %s", SMTP_HOST, SMTP_PORT, e)
        sys.exit(1)

    log.info("Briefing delivered to: %s", ", ".join(RECIPIENT_EMAILS))


def sendFailureAlert(errorMessage, logTail):
    """
    Sends a plain-text failure notification to the developer.
    Called from main.py when any unhandled exception or fatal error occurs.
    Fails silently if SMTP is not configured -- logs the alert locally instead.
    @param errorMessage (str) - short description of what went wrong
    @param logTail (str) - last N lines of pipeline.log to include in the email
    @returns None
    """
    if not DEVELOPER_EMAIL:
        log.error("DEVELOPER_EMAIL not set -- cannot send failure alert. Error was: %s", errorMessage)
        return

    if not SMTP_USER or not SMTP_PASSWORD:
        log.error(
            "SMTP not configured -- cannot send failure alert. Error was: %s", errorMessage
        )
        return

    today = datetime.date.today()
    dateStr = f"{today.day} {today.strftime('%B %Y')}"
    subject = f"[ACTION REQUIRED] Tech Briefing Pipeline Failed - {dateStr}"

    body = (
        f"The Cobaltix Tech Briefing pipeline failed on {dateStr}.\n\n"
        f"Error:\n{errorMessage}\n\n"
        f"---\nLast log entries:\n\n{logTail}"
    )

    msg = MIMEMultipart()
    msg["From"]    = SMTP_USER
    msg["To"]      = DEVELOPER_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        _smtpSend([DEVELOPER_EMAIL], msg)
        log.info("Failure alert sent to %s.", DEVELOPER_EMAIL)
    except Exception as e:
        # Alert sending itself failed -- log it and move on, don't raise
        log.error("Could not send failure alert to %s: %s", DEVELOPER_EMAIL, e)
