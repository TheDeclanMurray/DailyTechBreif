"""
Tech Briefing Pipeline -- entry point.
Fetch newsletter emails -> summarise with Claude -> convert to MP3 -> email to recipients.
Any unhandled failure triggers a plain-text alert email to the developer.
"""

import sys
import logging
import traceback

from src.logger import setupLogging, readLogTail
from src.gmail_client import fetchNewsletterEmails
from src.summarizer import summarizeEmails
from src.tts import convertToMp3
from src.mailer import sendBriefing, sendFailureAlert


def main():
    """
    Runs the full pipeline: Gmail fetch -> Claude summary -> TTS -> email delivery.
    @returns None
    @throws SystemExit on any fatal error (propagated from sub-modules)
    """
    log = logging.getLogger("tech_briefing")

    log.info("Cobaltix Tech Briefing Pipeline starting.")

    # Step 1: Pull newsletter emails from Gmail
    emails = fetchNewsletterEmails()

    if not emails:
        log.info("No emails found for configured senders in the past day. "
                 "Check NEWSLETTER_SENDERS in .env and confirm emails arrived.")
        sys.exit(0)

    # Step 2: Summarise with Claude
    briefing = summarizeEmails(emails)

    if not briefing:
        log.warning("Summarisation returned empty -- nothing to deliver.")
        sys.exit(0)

    # Step 3: Log the script for reference
    log.info("Briefing script:\n\n%s\n", briefing)

    # Step 4: Convert to MP3
    mp3Path = convertToMp3(briefing)

    # Step 5: Email MP3 and written script to all recipients
    sendBriefing(briefing, mp3Path)

    log.info("Pipeline complete.")


if __name__ == "__main__":
    # Logging must be set up before anything else so all modules write to the file
    setupLogging()
    log = logging.getLogger("tech_briefing")

    try:
        main()
    except SystemExit as e:
        # sys.exit(0) is a clean exit (no emails, empty summary) -- do not alert
        if e.code != 0:
            errorMsg = f"Pipeline exited with code {e.code}. Check the log for details."
            log.error(errorMsg)
            sendFailureAlert(errorMsg, readLogTail(lineCount=50))
        sys.exit(e.code)
    except Exception as e:
        errorMsg = f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}"
        log.error("Unhandled exception: %s", errorMsg)
        sendFailureAlert(errorMsg, readLogTail(lineCount=50))
        sys.exit(1)
