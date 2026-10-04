#!/usr/bin/env python3
"""
Interactive Setup Script for Inebotten
Guides the user through initial configuration without editing .env manually.
"""

import os
import sys
import shutil
import getpass
import warnings
from pathlib import Path
from core.config_schema import settings_path, update_settings, validate_settings
from utils.json_storage import hermes_home_path

# ANSI colors for better UX
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def clear_screen():
    # ANSI clear-screen sequence; avoids shell execution for a cosmetic action.
    print("\033[2J\033[H", end="")

def print_header():
    print(f"{Colors.BOLD}{Colors.BLUE}")
    print("============================================================")
    print("      _____             _           _   _                  ")
    print("     |_   _|           | |         | | | |                 ")
    print("       | |  _ __   ___ | |__   ___ | |_| |_ ___ _ __       ")
    print("       | | | '_ \\ / _ \\| '_ \\ / _ \\| __| __/ _ \\ '_ \\      ")
    print("      _| |_| | | |  __/| |_) | (_) | |_| ||  __/ | | |     ")
    print("     |_____|_| |_|\\___||_.__/ \\___/ \\__|\\__\\___|_| |_|     ")
    print("                                                           ")
    print("             INTERACTIVE SETUP WIZARD                      ")
    print("============================================================")
    print(f"{Colors.ENDC}")

def get_input(prompt, default=None, required=False):
    if default:
        p = f"{Colors.CYAN}{prompt}{Colors.ENDC} [{Colors.GREEN}{default}{Colors.ENDC}]: "
    else:
        p = f"{Colors.CYAN}{prompt}{Colors.ENDC}: "
    
    while True:
        val = input(p).strip()
        if not val and default:
            return default
        if not val and required:
            print(f"{Colors.FAIL}Error: This field is required.{Colors.ENDC}")
            continue
        return val


def get_secret(prompt, required=False):
    while True:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                value = getpass.getpass(f"{Colors.CYAN}{prompt}{Colors.ENDC}: ").strip()
        except getpass.GetPassWarning as exc:
            raise RuntimeError("Hidden credential input requires an interactive terminal.") from exc
        if value or not required:
            return value
        print(f"{Colors.FAIL}Error: This field is required.{Colors.ENDC}")

def check_dependencies():
    print(f"\n{Colors.BOLD}Step 1: Python environment{Colors.ENDC}")
    print("Use a project virtual environment; this setup does not install packages.")
    print(f"  {Colors.CYAN}python3 -m venv .venv312{Colors.ENDC}")
    print(f"  {Colors.CYAN}.venv312/bin/python -m pip install -r requirements.txt{Colors.ENDC}")

def setup_discord():
    print(f"\n{Colors.BOLD}Step 2: Discord Configuration{Colors.ENDC}")
    print("To get your Discord User Token:")
    print("  1. Open Discord in browser & Login")
    print("  2. Press F12 -> Application tab")
    print("  3. Storage -> Local Storage -> https://discord.com")
    print("  4. Find 'token' (may need to toggle filter or reload)")
    print(f"  {Colors.WARNING}WARNING: NEVER share your token with anyone!{Colors.ENDC}")
    
    token = get_secret("Enter your Discord User Token", required=True)
    return token

def setup_ai():
    print(f"\n{Colors.BOLD}Step 3: AI Provider Configuration{Colors.ENDC}")
    print("Choose your AI engine:")
    print("  1. LM Studio (Local, Free, requires LM Studio running)")
    print("  2. OpenRouter (Cloud, high quality, requires API key)")
    
    choice = get_input("Selection (1/2)", "1")
    
    config = {}
    if choice == "2":
        config['AI_PROVIDER'] = "openrouter"
        config['OPENROUTER_API_KEY'] = get_secret("Enter your OpenRouter API Key", required=True)
        default_model = os.getenv("OPENROUTER_MODEL", "google/gemma-4-31b-it:free")
        config['OPENROUTER_MODEL'] = get_input("Enter model name", default_model)
    else:
        config['AI_PROVIDER'] = "lm_studio"
        default_url = os.getenv("HERMES_API_URL", "http://127.0.0.1:3000/api/chat")
        config['HERMES_API_URL'] = get_input("LM Studio API URL", default_url)
    
    return config

def setup_google_calendar():
    print(f"\n{Colors.BOLD}Step 4: Google Calendar (Optional){Colors.ENDC}")
    choice = get_input("Enable Google Calendar integration?", "n").lower()
    
    if choice == 'y':
        print("\nTo enable Google Calendar:")
        print("  1. Go to Google Cloud Console")
        print("  2. Create a Project & Enable Calendar API")
        print("  3. Create OAuth 2.0 Desktop Client ID")
        print("  4. Download JSON and rename to 'client_secret.json'")
        
        path = get_input("Path to client_secret.json (or press Enter to skip for now)", "")
        if path and os.path.exists(path):
            hermes_data = hermes_home_path() / "google_credentials"
            hermes_data.mkdir(parents=True, exist_ok=True)
            shutil.copy(path, hermes_data / "client_secret.json")
            print(f"{Colors.GREEN}✓ Credential file copied to {hermes_data}{Colors.ENDC}")
            print(f"You will need to run 'python3 scripts/auth_gcal.py' later to authorize.")
            
            cal_id = get_input("Enter your Google Calendar ID (usually your email)", "primary")
            return {'GCAL_ENABLED': 'True', 'GOOGLE_CALENDAR_ID': cal_id}
        else:
            print(f"{Colors.WARNING}Skipping credential copy. You can do this manually later.{Colors.ENDC}")
        return {'GCAL_ENABLED': 'False'}
    return {'GCAL_ENABLED': 'False'}

def setup_access():
    from core.access_policy import describe_access_settings
    print('\nKalendertilgang: 1 = behold delt legacy-kalender, 2 = privat bruker, 3 = godkjent gruppe.')
    choice = get_input('Velg kalenderområde', '1')
    mode = {'1': 'legacy_shared', '2': 'private_user', '3': 'approved_group'}.get(choice)
    if mode is None:
        raise RuntimeError('Ugyldig kalenderområde.')
    values = {'CALENDAR_MODE': mode}
    if mode != 'legacy_shared':
        values['CALENDAR_OWNER_ID'] = get_input('Eierens Discord-bruker-ID', required=True)
    if mode == 'approved_group':
        values['CALENDAR_COLLABORATORS'] = get_input('Godkjente bruker-ID-er, kommaseparert')
        values['CALENDAR_GROUP_CHANNELS'] = get_input('Godkjente kanal-ID-er, kommaseparert', required=True)
    print('Invokasjon: 1 = legacy-regler, 2 = eksplisitte brukere og gruppekanaler.')
    invocation = get_input('Velg invokasjonsmodus', '2')
    if invocation not in ('1', '2'):
        raise RuntimeError('Ugyldig invokasjonsmodus.')
    values['INVOCATION_MODE'] = 'allowlist' if invocation == '2' else 'legacy'
    values['ALLOWED_USERS'] = get_input('Tillatte bruker-ID-er, kommaseparert', required=invocation == '2')
    values['ALLOWED_CHANNELS'] = get_input('Tillatte gruppekanal-ID-er, kommaseparert; tomt avviser grupper i allowlist-modus')
    errors = validate_settings(values)
    if errors:
        raise RuntimeError('; '.join(error['field'] + ': ' + error['reason'] for error in errors))
    print(describe_access_settings(values))
    return values

def generate_env(discord_token, ai_config, gcal_config, access_config=None):
    try:
        env_path = settings_path()
    except ValueError:
        print(f"  {Colors.FAIL}HERMES_HOME must name a configuration directory.{Colors.ENDC}")
        return False
    print(f"\n{Colors.BOLD}Step 5: Updating private settings at {env_path}{Colors.ENDC}")
    changes = {"DISCORD_USER_TOKEN": discord_token, **ai_config, **gcal_config, **(access_config or {})}
    errors = validate_settings(changes)
    if errors:
        for error in errors:
            print(f"  {Colors.FAIL}{error['field']}: {error['reason']}{Colors.ENDC}")
        return False
    try:
        update_settings(env_path, changes)
    except (OSError, ValueError):
        print(f"  {Colors.FAIL}Settings could not be saved. Check the target path and permissions.{Colors.ENDC}")
        return False
    print(f"  {Colors.GREEN}✓ .env file generated successfully!{Colors.ENDC}")
    return True

def main():
    clear_screen()
    print_header()
    
    try:
        print(f"Configuration path: {settings_path()}")
    except ValueError:
        print(f"{Colors.FAIL}HERMES_HOME must name a configuration directory.{Colors.ENDC}")
        return 1

    try:
        check_dependencies()
        
        token = setup_discord()
        ai_config = setup_ai()
        gcal_config = setup_google_calendar()
        access_config = setup_access()
        
        if not generate_env(token, ai_config, gcal_config, access_config):
            sys.exit(1)
        
        print(f"\n{Colors.BOLD}{Colors.GREEN}============================================================{Colors.ENDC}")
        print(f"{Colors.BOLD}{Colors.GREEN}       SETUP COMPLETE! Inebotten is ready to roll.          {Colors.ENDC}")
        print(f"{Colors.BOLD}{Colors.GREEN}============================================================{Colors.ENDC}")
        print(f"\nTo start the bot:")
        print(f"  {Colors.CYAN}.venv312/bin/python scripts/run_both.py{Colors.ENDC}")
        print(f"\nNeed help? Check the {Colors.UNDERLINE}docs/{Colors.ENDC} directory.")
        print("")
        
    except KeyboardInterrupt:
        print(f"\n\n{Colors.FAIL}Setup cancelled.{Colors.ENDC}")
        sys.exit(1)
    except RuntimeError as exc:
        print(f"{Colors.FAIL}{exc}{Colors.ENDC}")
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
