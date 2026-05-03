#!/usr/bin/env python3
"""
Interactive Setup Script for Inebotten
Guides the user through initial configuration without editing .env manually.
"""

import os
import sys
import shutil
from pathlib import Path

# Try to import dotenv, but don't fail if it's missing (we'll handle it later)
try:
    from dotenv import load_dotenv, set_key
    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False

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
    os.system('cls' if os.name == 'nt' else 'clear')

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

def check_dependencies():
    print(f"\n{Colors.BOLD}Step 1: Checking Dependencies{Colors.ENDC}")
    required = [
        'discord.py-self', 'aiohttp', 'python-dotenv', 'google-api-python-client',
        'google-auth-oauthlib', 'google-auth-httplib2'
    ]
    missing = []
    
    for lib in required:
        try:
            if lib == 'google-api-python-client':
                __import__('googleapiclient')
            elif lib == 'google-auth-oauthlib':
                __import__('google_auth_oauthlib')
            elif lib == 'google-auth-httplib2':
                __import__('google_auth_httplib2')
            elif lib == 'discord.py-self':
                __import__('discord')
            elif lib == 'python-dotenv':
                __import__('dotenv')
            else:
                __import__(lib.replace('-', '_'))
            print(f"  {Colors.GREEN}✓{Colors.ENDC} {lib} is installed")
        except ImportError:
            missing.append(lib)
            print(f"  {Colors.FAIL}✗{Colors.ENDC} {lib} is missing")
    
    if missing:
        print(f"\n{Colors.WARNING}Some dependencies are missing.{Colors.ENDC}")
        choice = get_input("Would you like to install them now?", "y").lower()
        if choice == 'y':
            import subprocess
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)
                print(f"{Colors.GREEN}Dependencies installed successfully!{Colors.ENDC}")
            except subprocess.CalledProcessError:
                print(f"\n{Colors.FAIL}Failed to install dependencies automatically.{Colors.ENDC}")
                print(f"{Colors.WARNING}Hint: Your system may be protecting its Python environment.{Colors.ENDC}")
                print(f"To fix this manually, run:")
                print(f"  {Colors.CYAN}pip install --break-system-packages {' '.join(missing)}{Colors.ENDC}")
                
                cont = get_input("\nWould you like to continue with setup anyway?", "y").lower()
                if cont != 'y':
                    sys.exit(1)
            except Exception as e:
                print(f"{Colors.FAIL}An unexpected error occurred: {e}{Colors.ENDC}")
                sys.exit(1)
        else:
            print(f"{Colors.WARNING}Skipping dependency installation. Ensure they are installed manually.{Colors.ENDC}")
    else:
        print(f"{Colors.GREEN}All core dependencies are satisfied.{Colors.ENDC}")

def setup_discord():
    print(f"\n{Colors.BOLD}Step 2: Discord Configuration{Colors.ENDC}")
    print("To get your Discord User Token:")
    print("  1. Open Discord in browser & Login")
    print("  2. Press F12 -> Application tab")
    print("  3. Storage -> Local Storage -> https://discord.com")
    print("  4. Find 'token' (may need to toggle filter or reload)")
    print(f"  {Colors.WARNING}WARNING: NEVER share your token with anyone!{Colors.ENDC}")
    
    default_token = os.getenv("DISCORD_USER_TOKEN", "")
    token = get_input("Enter your Discord User Token", default=default_token, required=True)
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
        default_key = os.getenv("OPENROUTER_API_KEY", "")
        config['OPENROUTER_API_KEY'] = get_input("Enter your OpenRouter API Key", default=default_key, required=True)
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
            hermes_data = Path.home() / ".hermes" / "google_credentials"
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

def generate_env(discord_token, ai_config, gcal_config):
    print(f"\n{Colors.BOLD}Step 5: Generating .env file{Colors.ENDC}")
    
    env_path = Path(".env")
    example_path = Path(".env.example")
    
    if env_path.exists():
        backup = env_path.with_suffix(".env.bak")
        shutil.copy(env_path, backup)
        os.chmod(backup, 0o600)
        print(f"  {Colors.WARNING}Existing .env backed up to .env.bak{Colors.ENDC}")

    # Read example or create new
    lines = []
    if example_path.exists():
        with open(example_path, "r") as f:
            lines = f.readlines()
    else:
        # Minimal template if example missing
        lines = [
            "DISCORD_USER_TOKEN=\n",
            "AI_PROVIDER=lm_studio\n"
        ]

    new_lines = []
    for line in lines:
        if line.startswith("DISCORD_USER_TOKEN="):
            new_lines.append(f"DISCORD_USER_TOKEN={discord_token}\n")
        elif line.startswith("AI_PROVIDER="):
            new_lines.append(f"AI_PROVIDER={ai_config['AI_PROVIDER']}\n")
        elif line.startswith("OPENROUTER_API_KEY=") and 'OPENROUTER_API_KEY' in ai_config:
            new_lines.append(f"OPENROUTER_API_KEY={ai_config['OPENROUTER_API_KEY']}\n")
        elif line.startswith("OPENROUTER_MODEL=") and 'OPENROUTER_MODEL' in ai_config:
            new_lines.append(f"OPENROUTER_MODEL={ai_config['OPENROUTER_MODEL']}\n")
        elif line.startswith("HERMES_API_URL=") and 'HERMES_API_URL' in ai_config:
            new_lines.append(f"HERMES_API_URL={ai_config['HERMES_API_URL']}\n")
        elif line.startswith("GCAL_ENABLED="):
            new_lines.append(f"GCAL_ENABLED={gcal_config.get('GCAL_ENABLED', 'False')}\n")
        elif line.startswith("GOOGLE_CALENDAR_ID="):
            new_lines.append(f"GOOGLE_CALENDAR_ID={gcal_config.get('GOOGLE_CALENDAR_ID', 'primary')}\n")
        else:
            new_lines.append(line)

    # Create .env with restricted permissions
    try:
        # Create file with 0600 permissions
        fd = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.writelines(new_lines)
    except Exception as e:
        print(f"  {Colors.FAIL}Error writing .env file: {e}{Colors.ENDC}")
        return
    
    print(f"  {Colors.GREEN}✓ .env file generated successfully!{Colors.ENDC}")

def main():
    clear_screen()
    print_header()
    
    if os.path.exists(".env"):
        if HAS_DOTENV:
            load_dotenv()
        else:
            # Simple fallback parser if dotenv is missing
            try:
                with open(".env", "r") as f:
                    for line in f:
                        if "=" in line:
                            k, v = line.split("=", 1)
                            os.environ[k.strip()] = v.strip().strip('"').strip("'")
            except PermissionError:
                print(f"{Colors.WARNING}Warning: Permission denied when reading .env file. Skipping...{Colors.ENDC}")
            except Exception as e:
                print(f"{Colors.WARNING}Warning: Could not read .env file: {e}{Colors.ENDC}")

    # Check for write permissions early
    if not os.access(".", os.W_OK):
        print(f"\n{Colors.FAIL}Error: You do not have write permissions in this directory.{Colors.ENDC}")
        print(f"{Colors.WARNING}Hint: Since you are in /opt, you might need to run this with sudo or change ownership:{Colors.ENDC}")
        print(f"  {Colors.CYAN}sudo chown -R $USER:$USER {os.getcwd()}{Colors.ENDC}")
        sys.exit(1)

    try:
        check_dependencies()
        
        token = setup_discord()
        ai_config = setup_ai()
        gcal_config = setup_google_calendar()
        
        generate_env(token, ai_config, gcal_config)
        
        print(f"\n{Colors.BOLD}{Colors.GREEN}============================================================{Colors.ENDC}")
        print(f"{Colors.BOLD}{Colors.GREEN}       SETUP COMPLETE! Inebotten is ready to roll.          {Colors.ENDC}")
        print(f"{Colors.BOLD}{Colors.GREEN}============================================================{Colors.ENDC}")
        print(f"\nTo start the bot:")
        print(f"  {Colors.CYAN}python3 scripts/run_both.py{Colors.ENDC}")
        print(f"\nNeed help? Check the {Colors.UNDERLINE}docs/{Colors.ENDC} directory.")
        print("")
        
    except KeyboardInterrupt:
        print(f"\n\n{Colors.FAIL}Setup cancelled.{Colors.ENDC}")
        sys.exit(1)

if __name__ == "__main__":
    main()
