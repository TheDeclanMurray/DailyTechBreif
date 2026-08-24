"""
Claude API summarisation -- takes email content and returns a spoken briefing script.
The system prompt is sent in the system field (better caching, cleaner separation).
The email content is sent in the user turn with ephemeral cache_control so repeated
runs with similar content benefit from prompt caching.
"""

import sys
import logging
import anthropic

from src.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

log = logging.getLogger("tech_briefing")

# Rough character limit before we truncate to avoid hitting context limits.
MAX_CONTENT_CHARS = 150_000


def formatEmailsForPrompt(emails):
    """
    Formats a list of email dicts into a single plaintext block for the user turn.
    @param emails (list[dict]) - list of dicts with keys: sender, subject, date, body
    @returns (str) formatted email content string
    @throws ValueError if emails is empty
    """
    if not emails:
        raise ValueError("emails list must not be empty")

    sections = []
    for i, email in enumerate(emails, start=1):
        section = (
            f"--- Email {i} ---\n"
            f"From:    {email['sender']}\n"
            f"Subject: {email['subject']}\n"
            f"Date:    {email['date']}\n\n"
            f"{email['body'].strip()}"
        )
        sections.append(section)

    combined = "\n\n".join(sections)

    # Truncate gracefully if content is enormous
    if len(combined) > MAX_CONTENT_CHARS:
        log.warning(
            "Email content is %s chars -- truncating to %s.",
            f"{len(combined):,}", f"{MAX_CONTENT_CHARS:,}"
        )
        combined = combined[:MAX_CONTENT_CHARS] + "\n\n[... content truncated ...]"

    return combined


def summarizeEmails(emails):
    """
    Sends email content to Claude and returns a spoken briefing script.
    System prompt goes in the system field for clean separation and caching.
    Email content in the user turn is marked ephemeral for prompt caching.
    @param emails (list[dict]) - fetched newsletter emails
    @returns (str) plain-prose briefing script ready for TTS
    @throws SystemExit if ANTHROPIC_API_KEY is missing or the API call fails
    """
    if not ANTHROPIC_API_KEY:
        log.error("ANTHROPIC_API_KEY is not set. Add it to your .env file.")
        sys.exit(1)

    if not emails:
        log.info("No emails to summarise -- nothing to send to Claude.")
        return ""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    emailContent = formatEmailsForPrompt(emails)
    userMessage = USER_PROMPT_TEMPLATE.format(email_content=emailContent)

    log.info("Sending %d email(s) to Claude (%s)...", len(emails), CLAUDE_MODEL)

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            # System prompt is static day-to-day -- Claude caches it automatically
            # after the first call, so we don't need cache_control here.
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": userMessage,
                            # Email content changes daily but caching it saves cost
                            # if the pipeline is re-run on the same day.
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                }
            ],
        )
    except anthropic.AuthenticationError:
        log.error("Invalid ANTHROPIC_API_KEY. Check your .env file.")
        sys.exit(1)
    except anthropic.APIError as e:
        log.error("Claude API call failed: %s", e)
        sys.exit(1)

    briefing = response.content[0].text

    # Log token usage to help monitor costs
    usage = response.usage
    log.info(
        "Summarisation complete. Tokens -- input: %s, output: %s, cache_read: %s, cache_write: %s",
        usage.input_tokens,
        usage.output_tokens,
        getattr(usage, "cache_read_input_tokens", "n/a"),
        getattr(usage, "cache_creation_input_tokens", "n/a"),
    )

    return briefing
