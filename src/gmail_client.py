"""
Gmail IMAP client -- fetches newsletter emails and labels the ones already summarized.

Uses IMAP with a Gmail App Password rather than the Gmail API's OAuth2 flow. The OAuth
approach worked but was structurally unsustainable for an unattended pipeline:
gmail.modify is a Google "restricted" scope, so an External consent screen had to either
stay in Testing mode -- where Google expires the refresh token after exactly 7 days --
or pass full verification including a paid third-party security assessment. An App
Password has neither constraint and is the same credential type src/mailer.py already
uses for SMTP delivery on this same account. See docs/DECISIONS.md (2026-09-15).

Gmail's IMAP extensions do the heavy lifting here:
  - X-GM-RAW    lets us keep using Gmail's own search syntax (from:/after:/-label:),
                so buildSearchQuery() is unchanged from the Gmail API implementation.
  - X-GM-MSGID  is a stable, account-global message id. We key off it instead of IMAP
                UIDs because a UID is only meaningful within one folder + UIDVALIDITY,
                and markEmailsAsProcessed() runs on a second connection minutes later.
  - X-GM-LABELS applies a real Gmail label via STORE, matching what the Gmail API's
                messages().modify() did.
"""

import sys
import email
import imaplib
import logging
import datetime
from email.header import decode_header, make_header

from src.config import (
    IMAP_HOST,
    IMAP_PORT,
    IMAP_USER,
    IMAP_PASSWORD,
    NEWSLETTER_SENDERS,
    LOOKBACK_DAYS,
    PROCESSED_LABEL_NAME,
)

log = logging.getLogger("tech_briefing")

# Max emails to fetch per sender to avoid huge payloads going into the Claude prompt.
MAX_RESULTS_PER_SENDER = 5

# imaplib's default line cap is 10,000 bytes, which a full newsletter body blows past
# instantly -- the fetch then dies with "got more than 10000 bytes". Raised well above
# any plausible single message.
imaplib._MAXLINE = 10_000_000


def buildImapConnection():
    """
    Opens an authenticated IMAP4_SSL connection to Gmail and selects the All Mail folder.
    @returns imaplib.IMAP4_SSL -- connected, logged in, with All Mail selected
    @throws SystemExit if credentials are missing or Gmail rejects the login
    """
    if not IMAP_USER or not IMAP_PASSWORD:
        log.error(
            "IMAP_USER/IMAP_PASSWORD are not set. They default to SMTP_USER/SMTP_PASSWORD "
            "-- set those in .env locally, or the SSM parameters on Lambda."
        )
        sys.exit(1)

    try:
        conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    except Exception as e:
        log.error("Could not connect to %s:%s -- %s", IMAP_HOST, IMAP_PORT, e)
        sys.exit(1)

    try:
        conn.login(IMAP_USER, IMAP_PASSWORD)
    except imaplib.IMAP4.error as e:
        # Almost always a revoked/mistyped App Password, or 2-Step Verification being
        # turned off on the account (which invalidates every App Password at once).
        log.error(
            "IMAP login failed for '%s': %s. Confirm the Gmail App Password is still "
            "valid and that 2-Step Verification is enabled on the account.", IMAP_USER, e
        )
        sys.exit(1)

    folder = findAllMailFolder(conn)
    status, _ = conn.select(f'"{folder}"', readonly=False)
    if status != "OK":
        log.error("Could not select IMAP folder '%s'.", folder)
        sys.exit(1)

    return conn


def findAllMailFolder(conn):
    """
    Locates Gmail's "All Mail" folder, which is what makes IMAP search cover the whole
    account the way the Gmail API's messages().list() did -- INBOX alone would silently
    miss anything already archived. The folder's display name is localised (e.g.
    "[Gmail]/Tous les messages"), so this matches on the RFC 6154 \\All special-use flag
    rather than the name, falling back to the English default.
    @param conn (imaplib.IMAP4_SSL) - connected, logged-in IMAP connection
    @returns (str) mailbox name to pass to SELECT
    """
    try:
        status, mailboxes = conn.list()
        if status == "OK":
            for raw in mailboxes:
                line = raw.decode("utf-8", errors="replace")
                # Format: (\HasNoChildren \All) "/" "[Gmail]/All Mail"
                if "\\All" in line:
                    return line.split(' "/" ')[-1].strip('"')
    except Exception as e:
        log.warning("IMAP LIST failed (%s) -- falling back to the default All Mail name.", e)

    log.warning("No \\All mailbox found -- falling back to '[Gmail]/All Mail'.")
    return "[Gmail]/All Mail"


def buildSearchQuery(senderEmail):
    """
    Constructs a Gmail search query for a specific sender within LOOKBACK_DAYS.
    Excludes messages already tagged with PROCESSED_LABEL_NAME, so a message summarized
    on a previous run doesn't get re-fetched and re-summarized on the next one.
    Passed to IMAP via X-GM-RAW, so this stays Gmail's own search syntax, unchanged from
    the Gmail API implementation.
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


def ensureProcessedLabel(conn):
    """
    Makes sure PROCESSED_LABEL_NAME exists as a Gmail label. Gmail exposes labels as
    IMAP folders, so CREATE is what makes one. An already-existing label comes back as
    a NO response (or raises), which is the normal case on every run after the first and
    is deliberately ignored.
    @param conn (imaplib.IMAP4_SSL) - connected, logged-in IMAP connection
    @returns None
    """
    try:
        status, _ = conn.create(f'"{PROCESSED_LABEL_NAME}"')
        if status == "OK":
            log.info("Created Gmail label '%s'.", PROCESSED_LABEL_NAME)
    except imaplib.IMAP4.error:
        # Gmail raises rather than returning NO on some paths -- either way the label
        # already exists, which is exactly the state we wanted.
        pass


def findUidByMessageId(conn, gmailMessageId):
    """
    Resolves a stable Gmail message id (X-GM-MSGID) back to an IMAP UID in the currently
    selected folder. Needed because STORE addresses messages by UID, but a UID is only
    valid within one folder + UIDVALIDITY -- the msgid survives the reconnect that
    markEmailsAsProcessed() does after delivery.
    @param conn (imaplib.IMAP4_SSL) - connected IMAP connection with a folder selected
    @param gmailMessageId (str) - X-GM-MSGID value captured at fetch time
    @returns (str|None) the UID as a string, or None if the message can't be found
    @throws ValueError if gmailMessageId is empty
    """
    if not gmailMessageId:
        raise ValueError("gmailMessageId must be a non-empty string")

    status, data = conn.uid("SEARCH", "X-GM-MSGID", str(gmailMessageId))
    if status != "OK" or not data or not data[0]:
        return None
    return data[0].split()[0].decode()


def markMessageProcessed(conn, uid):
    """
    Applies the processed label to a single message so future queries skip it.
    @param conn (imaplib.IMAP4_SSL) - connected IMAP connection with a folder selected
    @param uid (str) - IMAP UID of the message to label
    @returns None
    @throws ValueError if uid is empty
    @throws imaplib.IMAP4.error if Gmail rejects the STORE
    """
    if not uid:
        raise ValueError("uid must be a non-empty string")

    status, _ = conn.uid("STORE", uid, "+X-GM-LABELS", f'("{PROCESSED_LABEL_NAME}")')
    if status != "OK":
        raise imaplib.IMAP4.error(f"STORE +X-GM-LABELS failed for uid {uid}")


def decodeMimeHeader(rawValue):
    """
    Decodes a MIME encoded-word header (RFC 2047) into plain text -- newsletter subjects
    routinely arrive as "=?UTF-8?B?...?=" and would otherwise reach the briefing verbatim.
    @param rawValue (str|None) - raw header value from the parsed message
    @returns (str) decoded header text, or empty string if rawValue is falsy
    """
    if not rawValue:
        return ""
    try:
        return str(make_header(decode_header(rawValue)))
    except Exception:
        # A malformed encoded-word shouldn't cost us the whole email.
        return str(rawValue)


def extractPlainText(message):
    """
    Extracts the plain-text body from a parsed email message.
    Handles both single-part and multipart messages, preferring text/plain and skipping
    anything marked as an attachment.
    @param message (email.message.Message) - parsed message from email.message_from_bytes
    @returns (str) decoded plain-text body, or empty string if none found
    """
    if message is None:
        return ""

    if message.is_multipart():
        # Walk the whole tree -- newsletters nest text/plain inside multipart/alternative
        # inside multipart/mixed often enough that checking only the top level misses it.
        for part in message.walk():
            if part.get_content_type() != "text/plain":
                continue
            if "attachment" in str(part.get("Content-Disposition", "")).lower():
                continue
            decoded = _decodePayload(part)
            if decoded:
                return decoded
        return ""

    if message.get_content_type() == "text/plain":
        return _decodePayload(message)

    return ""


def _decodePayload(part):
    """
    Decodes one message part's payload to a string using its declared charset.
    @param part (email.message.Message) - a single (non-multipart) message part
    @returns (str) decoded text, or empty string if the part has no payload
    """
    payload = part.get_payload(decode=True)
    if not payload:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        # Unknown/bogus charset label -- utf-8 with replacement still beats dropping it.
        return payload.decode("utf-8", errors="replace")


def fetchNewsletterEmails():
    """
    Fetches newsletter emails from Gmail over IMAP for all configured senders.
    @returns (list[dict]) list of dicts with keys: id, sender, subject, date, body
        ("id" is the Gmail X-GM-MSGID, consumed later by markEmailsAsProcessed)
    @throws SystemExit on fatal connection/auth errors
    """
    if not NEWSLETTER_SENDERS:
        log.error("NEWSLETTER_SENDERS is empty. Set it in .env (comma-separated email addresses).")
        sys.exit(1)

    conn = buildImapConnection()
    allEmails = []

    try:
        for sender in NEWSLETTER_SENDERS:
            query = buildSearchQuery(sender)
            log.info("Searching for emails from '%s' (last %d days)...", sender, LOOKBACK_DAYS)

            try:
                status, data = conn.uid("SEARCH", "X-GM-RAW", query.encode("utf-8"))
            except imaplib.IMAP4.error as e:
                log.error("IMAP search failed for sender '%s': %s -- skipping.", sender, e)
                continue

            if status != "OK" or not data or not data[0]:
                log.info("Found 0 message(s) from '%s'.", sender)
                continue

            # Newest messages sit at the end of the UID list -- take the most recent N.
            uids = data[0].split()[-MAX_RESULTS_PER_SENDER:]
            log.info("Found %d message(s) from '%s'.", len(uids), sender)

            for uid in uids:
                parsed = _fetchOneMessage(conn, uid.decode())
                if parsed:
                    parsed["sender"] = sender
                    allEmails.append(parsed)
    finally:
        _closeQuietly(conn)

    log.info("Total emails fetched: %d", len(allEmails))
    return allEmails


def _fetchOneMessage(conn, uid):
    """
    Fetches and parses a single message by UID, pulling its Gmail message id in the same
    round trip so the caller can label it later without re-deriving it.
    BODY.PEEK[] rather than BODY[] so fetching doesn't mark the newsletter as read.
    @param conn (imaplib.IMAP4_SSL) - connected IMAP connection with a folder selected
    @param uid (str) - IMAP UID to fetch
    @returns (dict|None) dict with id/subject/date/body, or None if unusable
    """
    try:
        status, data = conn.uid("FETCH", uid, "(X-GM-MSGID BODY.PEEK[])")
    except imaplib.IMAP4.error as e:
        log.warning("Could not fetch message uid=%s: %s -- skipping.", uid, e)
        return None

    if status != "OK" or not data or not isinstance(data[0], tuple):
        log.warning("Unexpected FETCH response for uid=%s -- skipping.", uid)
        return None

    # data[0] is (metadata_bytes, raw_rfc822_bytes); X-GM-MSGID rides in the metadata.
    metadata = data[0][0].decode("utf-8", errors="replace")
    gmailMessageId = _parseGmailMessageId(metadata)
    if not gmailMessageId:
        log.warning("No X-GM-MSGID in FETCH response for uid=%s -- skipping.", uid)
        return None

    message = email.message_from_bytes(data[0][1])
    subject = decodeMimeHeader(message.get("Subject")) or "(no subject)"
    date    = decodeMimeHeader(message.get("Date")) or "(unknown date)"
    body    = extractPlainText(message)

    if not body:
        log.warning("No plain-text body for '%s' -- skipping.", subject)
        return None

    return {"id": gmailMessageId, "subject": subject, "date": date, "body": body}


def _parseGmailMessageId(metadata):
    """
    Pulls the X-GM-MSGID value out of an IMAP FETCH response's metadata string.
    @param metadata (str) - e.g. '12 (X-GM-MSGID 1794513... BODY[] {84321}'
    @returns (str|None) the numeric message id, or None if absent
    """
    marker = "X-GM-MSGID"
    if marker not in metadata:
        return None

    after = metadata.split(marker, 1)[1].strip()
    digits = ""
    for char in after:
        if char.isdigit():
            digits += char
        elif digits:
            # Stop at the first non-digit after the number has started, so the
            # byte-count in "BODY[] {84321}" later in the line can't be picked up.
            break
    return digits or None


def _closeQuietly(conn):
    """
    Closes and logs out an IMAP connection without letting teardown errors mask a real
    failure from the work that just ran.
    @param conn (imaplib.IMAP4_SSL) - connection to tear down
    @returns None
    """
    for step in (conn.close, conn.logout):
        try:
            step()
        except Exception:
            pass


def markEmailsAsProcessed(emails):
    """
    Labels each of the given emails as processed in Gmail, so buildSearchQuery()
    excludes them on the next run. Deliberately called only AFTER a briefing has been
    successfully delivered (see main.py) -- labeling at fetch time instead would mark an
    email as handled even if summarization or delivery failed later, permanently losing
    it from future runs.
    @param emails (list[dict]) - email dicts as returned by fetchNewsletterEmails(),
        each must have an "id" key (the Gmail X-GM-MSGID)
    @returns None
    @throws ValueError if emails is empty
    """
    if not emails:
        raise ValueError("emails must be a non-empty list")

    conn = buildImapConnection()
    labeled = 0

    try:
        ensureProcessedLabel(conn)

        for item in emails:
            try:
                uid = findUidByMessageId(conn, item["id"])
                if not uid:
                    log.warning("Could not resolve message id=%s to a UID.", item["id"])
                    continue
                markMessageProcessed(conn, uid)
                labeled += 1
            except (imaplib.IMAP4.error, ValueError) as e:
                # Non-fatal -- worst case this one email gets re-summarized next run,
                # which is the same behavior as before this feature existed.
                log.warning("Could not label message id=%s as processed: %s", item["id"], e)
    finally:
        _closeQuietly(conn)

    log.info("Marked %d email(s) as processed.", labeled)
