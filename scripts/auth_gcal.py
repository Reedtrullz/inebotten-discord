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
# Check both possible locations for credentials
CREDENTIALS_PATH = HERMES_HOME / "google_credentials" / "client_secret.json"
ALT_CREDENTIALS_PATH = Path("client_secret.json")

def main():
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
            
            target_cred = CREDENTIALS_PATH if CREDENTIALS_PATH.exists() else ALT_CREDENTIALS_PATH
            
            if not target_cred.exists():
                print(f"Error: Could not find client_secret.json")
                print(f"Looked in: {CREDENTIALS_PATH} and {ALT_CREDENTIALS_PATH}")
                print("Please download your credentials from Google Cloud Console and place them there.")
                sys.exit(1)
            
            flow = InstalledAppFlow.from_client_secrets_file(str(target_cred), SCOPES)
            # Use console flow if browser not available, otherwise local server
            try:
                creds = flow.run_local_server(port=0)
            except Exception:
                print("Local server failed, trying console flow...")
                creds = flow.run_console()

        # Save the credentials for the next run
        HERMES_HOME.mkdir(parents=True, exist_ok=True)
        with open(TOKEN_PATH, 'w') as token:
            token.write(creds.to_json())
        print(f"Success! Token saved to {TOKEN_PATH}")
        print("Inebotten is now authorized to access your Google Calendar.")

if __name__ == '__main__':
    main()
