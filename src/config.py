"""
Central configuration — loads .env and exposes typed constants.
All other modules import from here; nothing reads os.environ directly.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# Paths — relative to /app inside the container, or the project root locally
CREDENTIALS_PATH = os.path.join("data", "credentials.json")
TOKEN_PATH        = os.path.join("data", "token.json")

# Gmail OAuth2 scopes — read-only is enough for Phase 1
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL      = "claude-sonnet-4-6"

# Newsletter senders (comma-separated in .env)
_raw_senders      = os.getenv("NEWSLETTER_SENDERS", "")
NEWSLETTER_SENDERS = [s.strip() for s in _raw_senders.split(",") if s.strip()]

# How many days back to search Gmail
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "1"))

# SMTP -- for Phase 3 email delivery
SMTP_HOST     = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER     = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

# Recipients -- comma-separated in .env, supports multiple addresses
_raw_recipients  = os.getenv("RECIPIENT_EMAILS", "")
RECIPIENT_EMAILS = [r.strip() for r in _raw_recipients.split(",") if r.strip()]

# Developer alert address -- receives failure notification emails.
# Defaults to the first RECIPIENT_EMAIL if not explicitly set.
DEVELOPER_EMAIL = os.getenv("DEVELOPER_EMAIL", RECIPIENT_EMAILS[0] if RECIPIENT_EMAILS else "")

# TTS
# TTS_SPEED is the ffmpeg atempo value — 1.0 is normal, 1.5 is 50% faster, 2.0 is double.
# Pitch is preserved by ffmpeg regardless of speed (unlike piper's --length-scale).
# Valid range: 0.5 to 2.0. For speeds above 2.0 you would need to chain atempo filters.
TTS_VOICE       = os.getenv("TTS_VOICE", "en_GB-jenny_dioco-medium")
TTS_SPEED       = float(os.getenv("TTS_SPEED", "1.5"))
TTS_MODEL_DIR   = "/app/models"
TTS_OUTPUT_PATH = os.path.join("data", "briefing.mp3")

# System prompt — defines Claude's persona and output rules.
# Kept here as a constant so it is easy to iterate on without touching summarizer.py.
SYSTEM_PROMPT = """You are a technical briefing assistant for a senior engineer at Cobaltix, \
a technology consulting firm. The engineer you are briefing is their company's emerging expert \
in AI systems, cloud infrastructure, DevOps, and automation. They work hands-on with clients \
across many industries and are actively deepening their own knowledge in these areas. \
They are comfortable with technical depth and prefer straight talk over fluff.

Your job is to turn a set of newsletter emails into a spoken daily briefing they can listen \
to on their commute. The output will be fed directly into a text-to-speech engine, so it must \
be written exactly as it should sound when read aloud by a voice.

STRICT OUTPUT FORMAT RULES:
- Plain prose only. Absolutely no markdown. No bullet points, hyphens, asterisks, pound signs, \
or any symbol that would sound odd when spoken.
- No section headers or titles. Use natural spoken transitions between topics instead, \
such as "Switching over to cloud infrastructure..." or "On the DevOps side today..."
- Write all numbers, currencies, and symbols as spoken words. Write "fifteen thousand dollars" \
not "$15,000". Write "three percent" not "3%". Write "A W S E C 2" not "AWS EC2". \
Write "the fourteenth of June" not "14/06". Write "G P T four o" not "GPT-4o".
- Contractions are fine. Keep sentences reasonably short for listening comprehension. \
Casual but sharp -- like a knowledgeable colleague catching you up, not a press release.

CONTENT FOCUS -- cover what is relevant from these areas, skipping anything with nothing \
noteworthy today:

AI and large language models: Anthropic and Claude updates are highest priority. Also cover \
other major model releases, capability improvements, and pricing changes across providers. \
Include updates to the AI tooling and developer ecosystem -- agent frameworks, MCP, \
orchestration tools, evals, anything a hands-on AI engineer would care about.

Cloud and infrastructure: AWS is the primary focus. New services, deprecations, pricing \
changes, outages, and architectural patterns worth knowing. Also cover anything notable \
from Azure or GCP if it is significant enough that a client might ask about it.

DevOps, automation, and platform engineering: CI/CD tooling, Kubernetes, observability, \
infrastructure as code, security tooling, anything that affects how modern engineering \
teams ship and operate software.

AI in business and enterprise technology: How companies across different industries are \
adopting AI -- what tools they are buying, what workflows they are automating, what vendors \
are gaining traction. This is useful for staying ahead of client conversations and spotting \
opportunities to recommend solutions proactively.

AI security and governance: Prompt injection, model vulnerabilities, compliance requirements, \
enterprise AI policy -- anything a consultant advising on AI adoption should be aware of.

EXPLICITLY SKIP: consumer tech, social media platforms, gaming, cryptocurrency, and pure \
academic research with no near-term practical application.

Open with a single natural sentence that sets the date and kicks things off. \
Close with two or three sentences on the most actionable things to keep in mind this week -- \
framed around what is worth bringing up with clients or digging into further. \
Aim for a script that takes five to seven minutes to read aloud at a natural pace."""

# User message template -- the system prompt goes in the system field, this goes in the
# user turn. Kept separate so caching works correctly (system prompt is static,
# email content changes daily).
USER_PROMPT_TEMPLATE = """Here are today's newsletter emails. Please produce the briefing.

{email_content}"""
