"""
One-time OAuth2 authentication flow for Gmail API.

Run this ONCE (before using the main pipeline) to generate data/token.json.
Inside Docker:  docker compose run --rm auth
Locally:        python -m src.auth

How it works:
  1. Prints an authorisation URL — copy it into any browser on your laptop.
  2. Google asks you to sign in and grant access.
  3. Your browser is redirected to localhost:8080 — the container catches it
     automatically via the port mapping in docker-compose.yml.
  4. token.json is written to data/ and all subsequent runs use it silently.

No manual code-pasting required — the local server handles the exchange.
"""

import http.server
import os
import sys
import urllib.parse
from google_auth_oauthlib.flow import InstalledAppFlow
from src.config import CREDENTIALS_PATH, TOKEN_PATH, GMAIL_SCOPES

# Google only accepts localhost/127.0.0.1 as loopback redirect URIs.
# The server itself binds to 0.0.0.0 so Docker port-forwarding can reach it.
_REDIRECT_URI = "http://localhost:8080/"


def runAuthFlow():
    """
    Launches a loopback OAuth2 consent flow on port 8080 and writes token.json.
    Prints a URL to visit in any browser — no browser needed on the server itself.
    @returns None
    @throws SystemExit if credentials.json is missing or the flow fails
    """

    if not os.path.exists(CREDENTIALS_PATH):
        print(
            f"[ERROR] credentials.json not found at '{CREDENTIALS_PATH}'.\n"
            f"        Download it from Google Cloud Console and place it in the data/ folder."
        )
        sys.exit(1)

    try:
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, GMAIL_SCOPES)
        flow.redirect_uri = _REDIRECT_URI
        authUrl, _ = flow.authorization_url(
            access_type="offline",  # request a refresh_token so we never need to re-auth
            prompt="consent",       # force consent screen so refresh_token is always issued
        )
    except Exception as e:
        print(f"[ERROR] Failed to build authorisation URL: {e}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("  GMAIL AUTHORISATION — copy this URL into your browser")
    print("=" * 60)
    print(f"\n{authUrl}\n")
    print("=" * 60)
    print("After granting access your browser will redirect to")
    print("localhost:8080 — waiting for the callback now...")
    print("=" * 60 + "\n")

    # Capture the authorisation code from the redirect callback.
    # Binds to 0.0.0.0 so Docker's port mapping can forward the request in.
    authCode = [None]
    authError = [None]

    class _CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in params:
                authCode[0] = params["code"][0]
                body = b"<html><body><h1>Authentication successful!</h1><p>You can close this tab.</p></body></html>"
            else:
                authError[0] = params.get("error", ["unknown error"])[0]
                body = f"<html><body><h1>Authentication failed: {authError[0]}</h1></body></html>".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass  # suppress request logs

    try:
        server = http.server.HTTPServer(("0.0.0.0", 8080), _CallbackHandler)
        server.handle_request()
    except Exception as e:
        print(f"[ERROR] Callback server failed: {e}")
        sys.exit(1)

    if authError[0]:
        print(f"[ERROR] Google returned an error: {authError[0]}")
        sys.exit(1)

    if not authCode[0]:
        print("[ERROR] No authorisation code received.")
        sys.exit(1)

    try:
        flow.fetch_token(code=authCode[0])
        creds = flow.credentials
    except Exception as e:
        print(f"[ERROR] Token exchange failed: {e}")
        sys.exit(1)

    os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
    with open(TOKEN_PATH, "w") as tokenFile:
        tokenFile.write(creds.to_json())

    print(f"[AUTH] Success! token.json written to '{TOKEN_PATH}'.")
    print("       You can now run the main pipeline:  docker compose run --rm tech-briefing")


if __name__ == "__main__":
    runAuthFlow()
