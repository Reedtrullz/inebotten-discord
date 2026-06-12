#!/usr/bin/env python3
"""
Google Calendar Authorization Script
Runs the OAuth2 flow to generate google_token.json
"""

import os
import sys
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# Scopes needed for the calendar
SCOPES = ["https://www.googleapis.com/auth/calendar"]


def resolve_auth_paths(hermes_home=None, token_path=None, credentials_path=None):
    """Resolve the same durable auth paths used by the running bot."""
    resolved_home = Path(
        hermes_home or os.getenv("HERMES_HOME", Path.home() / ".hermes")
    ).expanduser()
    resolved_token = Path(
        token_path or os.getenv("GCAL_TOKEN_PATH", resolved_home / "google_token.json")
    ).expanduser()
    resolved_credentials = Path(
        credentials_path
        or os.getenv("GCAL_CREDENTIALS_PATH", resolved_home / "credentials.json")
    ).expanduser()
    return resolved_home, resolved_token, resolved_credentials


def legacy_credentials_paths(hermes_home):
    return [
        hermes_home / "google_credentials" / "client_secret.json",
        Path("client_secret.json"),
    ]


def save_credentials(creds, token_path):
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.parent.chmod(0o700)
    fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as token:
        token.write(creds.to_json())
    token_path.chmod(0o600)


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(
        description="Google Calendar auth (headless support)"
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="Run auth without opening a browser"
    )
    parser.add_argument(
        "--hermes-home",
        help="Persistent Inebotten data directory. Docker/VPS usually uses /opt/apps/inebotten-discord/data.",
    )
    parser.add_argument("--token-path", help="Explicit google_token.json output path")
    parser.add_argument("--credentials-path", help="Explicit credentials.json input path")
    args = parser.parse_args(argv)
    hermes_home, token_path, credentials_path = resolve_auth_paths(
        args.hermes_home, args.token_path, args.credentials_path
    )
    
    print("=== Google Calendar Authorization ===")
    print(f"Data directory: {hermes_home}")
    print(f"Credentials path: {credentials_path}")
    print(f"Token path: {token_path}")
    
    creds = None
    
    # The file google_token.json stores the user's access and refresh tokens
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        print(f"Existing token found at {token_path}")

    # If there are no (valid) credentials available, let the user log in.
    if creds and not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing expired token...")
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Refresh failed: {e}")
                creds = None
        if creds and not creds.valid:
            print("Existing token is invalid and cannot be refreshed.")
            creds = None

    if not creds:
        print("Starting new authorization flow...")

        target_cred = credentials_path
        if not target_cred.exists():
            for legacy_path in legacy_credentials_paths(hermes_home):
                if legacy_path.exists():
                    target_cred = legacy_path
                    break

        if not target_cred.exists():
            print("Error: Could not find credentials.json")
            print(f"Expected: {credentials_path}")
            print("Download an OAuth Desktop client JSON from Google Cloud Console,")
            print("rename it to credentials.json, and place it in the data directory.")
            print()
            print("For Docker/VPS deployments, this is usually:")
            print("  /opt/apps/inebotten-discord/data/credentials.json")
            print()
            print("Then run:")
            print(
                "  HERMES_HOME=/opt/apps/inebotten-discord/data "
                "python3 scripts/auth_gcal.py --no-browser"
            )
            sys.exit(1)
            
        flow = InstalledAppFlow.from_client_secrets_file(str(target_cred), SCOPES)

        # Use local server for OAuth; fallback to manual flow for headless hosts.
        try:
            print("Attempting to open your browser for authorization (local server flow)...")
            if args.no_browser:
                raise Exception("User requested no-browser flow")
            creds = flow.run_local_server(port=0, open_browser=True)
        except Exception as e:
            print(f"Local server flow failed: {e}")
            print("Falling back to manual console authentication flow...")
            auth_url, _ = flow.authorization_url(
                prompt="consent", access_type="offline"
            )
            print(
                "Please open the following URL in a browser on any machine, "
                "authorize, and paste the resulting code below:"
            )
            print(auth_url)
            code = input("Enter verification code: ").strip()
            flow.fetch_token(code=code)
            creds = flow.credentials

    if creds and creds.valid:
        # Save the credentials for the next run, including refreshed tokens.
        save_credentials(creds, token_path)
        print(f"Success! Token saved to {token_path}")
        print("Inebotten is now authorized to access your Google Calendar.")
    else:
        print("Authorization did not produce a valid token.")
        sys.exit(1)

if __name__ == "__main__":
    main()
