"""
Central configuration — loads .env and exposes typed constants.
All other modules import from here; nothing reads os.environ directly.
"""

import os
import boto3
from dotenv import load_dotenv

load_dotenv()

# Set automatically by the Lambda runtime -- absent everywhere else (local dev via
# docker compose, CI). Used to branch between reading secrets from .env (local) and
# from SSM Parameter Store (Lambda), since Lambda has no .env file to load.
IS_LAMBDA = bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME"))

# SSM parameter namespace, e.g. "/daily-tech-brief" -- set by Terraform as a Lambda
# env var (see infra/lambda.tf); irrelevant locally since IS_LAMBDA gates its use.
SSM_PARAMETER_PREFIX = os.getenv("SSM_PARAMETER_PREFIX", "")

# Paths — relative to /var/task inside the Lambda container, or the project root locally.
# CREDENTIALS_PATH is only ever read by src/auth.py, which is run locally/via docker
# compose only (Lambda can't do an interactive OAuth browser redirect), so it never
# needs a Lambda-specific path. TOKEN_PATH does need one -- see the Lambda branch below.
CREDENTIALS_PATH = os.path.join("data", "credentials.json")
TOKEN_PATH        = os.path.join("data", "token.json")

# Gmail OAuth2 scopes — upgraded from gmail.readonly to gmail.modify (2026-08-28) so the
# pipeline can label a message as processed once summarized, see PROCESSED_LABEL_NAME below.
# Any token.json issued under the old readonly-only scope must be re-authed (delete
# TOKEN_PATH and re-run the auth flow) -- Google rejects modify calls against an old token.
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

# Gmail label applied to a message once it's been summarized, so the next run's search
# query can exclude it and avoid re-summarizing the same newsletter (see
# gmail_client.py's getOrCreateProcessedLabel()/buildSearchQuery()).
PROCESSED_LABEL_NAME = "tech-briefing/processed"

CLAUDE_MODEL = "claude-sonnet-4-6"

# Newsletter senders (comma-separated in .env)
_raw_senders      = os.getenv("NEWSLETTER_SENDERS", "")
NEWSLETTER_SENDERS = [s.strip() for s in _raw_senders.split(",") if s.strip()]

# How many days back to search Gmail -- default kept in sync with infra/variables.tf's
# lookback_days (also 4), so a missing env var behaves the same locally and on Lambda.
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "4"))

# SMTP -- for Phase 3 email delivery. SMTP_PASSWORD is a secret -- see the Secrets
# section below, which sets it (and ANTHROPIC_API_KEY) from .env or SSM depending on
# IS_LAMBDA rather than directly here alongside these non-secret SMTP values.
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")

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
# No TTS_OUTPUT_PATH -- the MP3 is only ever attached to the outgoing email and never
# read again afterward, so convertToMp3() pipes ffmpeg's output straight into memory
# instead of writing a file. Sidesteps the Lambda read-only-filesystem problem entirely
# rather than routing around it with a /tmp path (see docs/ISSUES-ENCOUNTERED.md).

# --- Secrets: ANTHROPIC_API_KEY, SMTP_PASSWORD, Gmail OAuth token ---
# Local/container dev reads these from .env like everything else above. Lambda has no
# .env file, so it fetches the same three values from SSM Parameter Store instead --
# see infra/ssm.tf for where they're seeded and infra/lambda.tf for SSM_PARAMETER_PREFIX.

def _fetchSsmParameter(name, decrypt=True):
    """
    Fetches one SSM Parameter Store value.

    Args:
        name (str): Full parameter name, e.g. "/daily-tech-brief/ANTHROPIC_API_KEY".
        decrypt (bool): Pass True for SecureString parameters (all of ours are).

    Returns:
        str: The parameter's value.

    Raises:
        botocore.exceptions.ClientError: If the parameter doesn't exist or SSM is
            unreachable (missing IAM permission, network issue, etc).
    """
    response = boto3.client("ssm").get_parameter(Name=name, WithDecryption=decrypt)
    return response["Parameter"]["Value"]


def persistGmailToken(tokenJson):
    """
    Persists a refreshed Gmail OAuth token so future runs can use it.

    Always writes to the local TOKEN_PATH (what gmail_client.py reads from). When
    running in Lambda, also writes the value back to SSM -- Lambda's filesystem is
    ephemeral across cold starts, so without this every cold start would keep reusing
    the pre-refresh token, forcing a redundant refresh call on every single invocation
    instead of reusing a still-valid access token (see the ignore_changes note on the
    gmail_token parameter in infra/ssm.tf, which exists specifically for this).

    Args:
        tokenJson (str): The token.json contents to persist, as returned by
            google.oauth2.credentials.Credentials.to_json().

    Returns:
        None

    Raises:
        ValueError: If tokenJson is empty or whitespace-only.
    """
    if not tokenJson or not tokenJson.strip():
        raise ValueError("tokenJson must be a non-empty JSON string")

    # Local write happens either way -- gmail_client.py always reads from TOKEN_PATH,
    # whether that's the real data/ dir locally or the /tmp bootstrap file in Lambda.
    with open(TOKEN_PATH, "w") as f:
        f.write(tokenJson)

    if IS_LAMBDA:
        boto3.client("ssm").put_parameter(
            Name=f"{SSM_PARAMETER_PREFIX}/GMAIL_TOKEN_JSON",
            Value=tokenJson,
            Type="SecureString",
            Overwrite=True,
        )


if IS_LAMBDA:
    ANTHROPIC_API_KEY = _fetchSsmParameter(f"{SSM_PARAMETER_PREFIX}/ANTHROPIC_API_KEY")
    SMTP_PASSWORD     = _fetchSsmParameter(f"{SSM_PARAMETER_PREFIX}/SMTP_PASSWORD")

    # gmail_client.py reads token.json from TOKEN_PATH -- point it at Lambda's one
    # writable location and seed it from SSM before anything tries to read it.
    TOKEN_PATH = "/tmp/token.json"
    with open(TOKEN_PATH, "w") as f:
        f.write(_fetchSsmParameter(f"{SSM_PARAMETER_PREFIX}/GMAIL_TOKEN_JSON"))
else:
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    SMTP_PASSWORD     = os.getenv("SMTP_PASSWORD", "")

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
