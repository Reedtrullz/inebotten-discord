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
SCOPES = ['https://www.googleapis.com/auth/calendar']

HERMES_HOME = Path(os.getenv("HERMES_HOME", Path.home() / ".hermes"))
TOKEN_PATH = HERMES_HOME / "google_token.json"
# Runtime GoogleCalendarManager expects this exact OAuth client file.
CREDENTIALS_PATH = HERMES_HOME / "credentials.json"
LEGACY_CREDENTIALS_PATHS = [
    HERMES_HOME / "google_credentials" / "client_secret.json",
    Path("client_secret.json"),
]

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Google Calendar auth (headless support)')
    parser.add_argument('--no-browser', action='store_true', help='Run auth without opening a browser')
    args = parser.parse_args()
    
    print("=== Google Calendar Authorization ===")
    
    creds = None
    
    # The file google_token.json stores the user's access and refresh tokens
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        print(f"Existing token found at {TOKEN_PATH}")

    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing expired token...")
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Refresh failed: {e}")
                creds = None
        
        if not creds:
            print("Starting new authorization flow...")
            
            target_cred = CREDENTIALS_PATH
            if not target_cred.exists():
                for legacy_path in LEGACY_CREDENTIALS_PATHS:
                    if legacy_path.exists():
                        target_cred = legacy_path
                        break
            
            if not target_cred.exists():
                print("Error: Could not find credentials.json")
                print(f"Expected: {CREDENTIALS_PATH}")
                print("Download an OAuth Desktop client JSON from Google Cloud Console,")
                print("rename it to credentials.json, and place it in ~/.hermes/.")
                sys.exit(1)
            
            flow = InstalledAppFlow.from_client_secrets_file(str(target_cred), SCOPES)
            
            # Use local server for the OAuth flow; fallback to manual flow for headless environments
            try:
                print("Attempting to open your browser for authorization (local server flow)...")
                # If user passed --no-browser, skip opening the browser
                if args.no_browser:
                    raise Exception('User requested no-browser flow')
                creds = flow.run_local_server(port=0, open_browser=True)
            except Exception as e:
                print(f"Local server flow failed: {e}")
                print("Falling back to manual console authentication flow...")
                # Manual flow: generate auth URL, ask user to open it elsewhere, then paste code
                auth_url, _ = flow.authorization_url(prompt='consent')
                print("Please open the following URL in a browser on any machine, authorize, and paste the resulting code below:")
                print(auth_url)
                code = input('Enter verification code: ').strip()
                flow.fetch_token(code=code)
                creds = flow.credentials
            
        # Save the credentials for the next run
        HERMES_HOME.mkdir(parents=True, exist_ok=True)
        HERMES_HOME.chmod(0o700)
        fd = os.open(TOKEN_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as token:
            token.write(creds.to_json())
        TOKEN_PATH.chmod(0o600)
        print(f"Success! Token saved to {TOKEN_PATH}")
        print("Inebotten is now authorized to access your Google Calendar.")

if __name__ == '__main__':
    main()
