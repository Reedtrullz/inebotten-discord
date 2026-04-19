# Inebotten Discord Bot - Windows App

A native Windows application for the Inebotten Discord selfbot with a simple GUI interface.

## Features

- 🖥️ **Native Windows App** - Double-click to run, no command prompt needed
- 🔑 **Easy Configuration** - GUI for entering API keys and settings
- 🤖 **AI Provider Selection** - Switch between LM Studio and OpenRouter
- 📊 **Live Output Log** - See bot output in real-time
- 💾 **Save Configuration** - Save your settings for next time
- ⏯️ **One-Click Start/Stop** - Easy bot control

## Requirements

- Windows 10 or later (64-bit)
- Python 3.10 or later
- PyInstaller for building the executable

## Quick Start

### Option 1: Use Pre-built Executable (Recommended)

If you have a pre-built `Inebotten.exe`:

1. Double-click `Inebotten.exe` to launch
2. Enter your Discord token and API key
3. Click "Start Bot"

### Option 2: Build from Source

#### Step 1: Install Python

1. Download Python 3.10+ from https://www.python.org/downloads/
2. During installation:
   - Check "Add Python to PATH"
   - Check "Install for all users" (optional)
   - Check "Associate .py files"

#### Step 2: Clone the Repository

```bash
git clone https://github.com/Reedtrullz/inebotten-discord.git
cd inebotten-discord
```

#### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
pip install pyinstaller
```

#### Step 4: Build the Executable

```bash
cd windows_app
python build.py
```

Or use the setup script:

```bash
windows_app\setup.bat
```

This will create `Inebotten.exe` in the `dist/` directory.

#### Step 5: Run the App

```bash
# Run from dist directory
dist\Inebotten.exe

# Or create a shortcut on your desktop
```

## Usage

### First Time Setup

1. **Launch the App**
   - Double-click `Inebotten.exe`
   - You may see a Windows SmartScreen warning (see below)

2. **Configure Settings**
   - **AI Provider**: Choose `lm_studio` (local) or `openrouter` (cloud)
   - **Discord Token**: Enter your Discord user token
   - **OpenRouter API Key**: (if using OpenRouter) Enter your API key
   - **Model**: Choose an AI model

3. **Save Configuration**
   - Click "Save Config" to save your settings

4. **Start the Bot**
   - Click "Start Bot"
   - Watch the output log for startup messages

5. **Stop the Bot**
   - Click "Stop Bot" when done

### Getting Your Discord Token

1. Open Discord in your browser
2. Press `F12` to open Developer Tools
3. Go to `Application` → `Local Storage` → `https://discord.com`
4. Find `token` and copy the value
5. Paste it into the app

### Getting Your OpenRouter API Key

1. Go to [https://openrouter.ai/keys](https://openrouter.ai/ai/keys)
2. Sign up or log in
3. Create a new API key
4. Copy the key (starts with `sk-or-`)
5. Paste it into the app

## Configuration

### AI Provider Options

**LM Studio (Local)**
- Requires LM Studio installed on your Windows PC
- Free to use
- Runs locally (no internet needed)
- Model: Your local model

**OpenRouter (Cloud)**
- Requires API key
- Pay-per-use (free models available)
- Requires internet connection
- 100+ models available

### Model Recommendations

**Free Models:**
- `google/gemma-3-4b-it:free` - Best Norwegian support
- `meta-llama/llama-3-8b-instruct:free` - Good general purpose
- `mistralai/mistral-7b-instruct:free` - Fast and creative

**Paid Models:**
- `anthropic/claude-3-haiku` - Best value (~$0.25/1M tokens)
- `openai/gpt-3.5-turbo` - Most reliable (~$0.50/1M tokens)
- `openai/gpt-4` - Best quality (~$30/1M tokens)

## Troubleshooting

### Windows SmartScreen Warning

**Problem:** "Windows protected your PC" warning when running the app

**Solution:**
1. Click "More info"
2. Click "Run anyway"
3. The app will now be trusted

### App Won't Open

**Problem:** App won't launch or crashes immediately

**Solutions:**
1. Check you're on Windows 10+ (64-bit)
2. Rebuild the executable: `cd windows_app && python build.py`
3. Check console logs for errors
4. Make sure you have all dependencies installed

### Bot Won't Start

**Problem:** Bot starts but stops immediately

**Solutions:**
1. Check your Discord token is valid
2. Check your OpenRouter API key (if using OpenRouter)
3. Make sure LM Studio is running (if using LM Studio)
4. Check the output log for error messages

### Missing Dependencies

**Problem:** App shows import errors

**Solutions:**
1. Install dependencies: `pip install -r requirements.txt`
2. Rebuild the executable: `cd windows_app && python build.py`
3. Make sure Python is in your PATH

### "Python not found" Error

**Problem:** App can't find Python

**Solutions:**
1. Install Python 3.10+ from https://www.python.org/downloads/
2. During installation, check "Add Python to PATH"
3. Rebuild the app
4. Or run from command prompt: `dist\Inebotten.exe`

## Advanced Usage

### Running from Command Prompt

If you prefer command prompt control:

```bash
# Run the executable directly
dist\Inebotten.exe

# Or from the build directory
cd dist
Inebotten.exe
```

### Viewing Logs

Logs are stored in:
```
C:\Users\YourUsername\.hermes\discord\logs\inebotten.log
```

View them:
```cmd
type C:\Users\YourUsername\.hermes\discord\logs\inebotten.log
```

Or open in Notepad:
```
notepad C:\Users\YourUsername\.hermes\discord\logs\inebotten.log
```

### Configuration Files

Settings are stored in:
```
C:\Users\YourUsername\.hermes\discord\.env                    # Bot configuration
C:\Users\YourUsername\.hermes\discord\launcher_config.json  # GUI configuration
C:\Users\YourUsername\.hermes\discord\data\                   # Calendar data
C:\Users\YourUsername\.hermes\discord\reminder_log.json      # Reminder log
```

## Building for Distribution

### Creating an Installer

Consider using tools like:
- **Inno Setup** - Free installer creator
- **NSIS** - Nullsoft Scriptable Install System
- **WiX Toolset** - Windows Installer XML

Example with Inno Setup:

```iss
[Setup]
AppName=Inebotten Discord Bot
AppVersion=2.0
DefaultDir={pf}\Inebotten
DefaultGroupName=Inebotten
OutputBaseFilename=Inebotten-Setup.exe
Compression=lzma
SolidCompression=yes

[Files]
Source: "dist\Inebotten.exe"; DestDir: "{app}\Inebotten.exe"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}\README.md"; Flags: ignoreversion

[Icons]
Name: "{userdesktop}\Inebotten"; Filename: "{userdesktop}\Inebotten.lnk"; Target: "{app}\Inebotten.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\Inebotten"; Filename: "{userdesktop}\Inebotten.lnk"; Target: "{app}\Inebotten.exe"; WorkingDir: "{app}"

[Run]
Filename: "{app}\Inebotten.exe"; Description: "Start Inebotten Discord Bot"
```

### Code Signing (Optional)

If you have a code signing certificate:

```bash
# Sign the executable
signtool sign /f "your-certificate.pfx" /p "password" dist\Inebotten.exe

# Verify the signature
signtool verify /pa dist\Inebotten.exe
```

## Performance

### Resource Usage

- **Memory:** ~100-200 MB
- **CPU:** Low when idle, moderate when processing messages
- **Disk:** ~50-100 MB for executable
- **Network:** Minimal (only for API calls)

### Optimization Tips

1. **Use LM Studio** for better performance (no network latency)
2. **Limit concurrent operations** to reduce CPU usage
3. **Close other apps** if experiencing slowdowns
4. **Use free models** to reduce API costs

## Updates

### Updating the App

When you update the bot code:

1. Pull latest changes:
   ```cmd
   cd C:\Users\YourUsername\Downloads\inebotten-discord
   git pull
   ```

2. Rebuild the executable:
   ```cmd
   cd windows_app
   python build.py
   ```

3. Replace the old executable:
   ```cmd
   del "C:\Program Files\Inebotten\Inebotten.exe"
   copy dist\Inebotten.exe "C:\Program Files\Inebotten\Inebotten.exe"
   ```

### Auto-Update (Future)

Consider adding auto-update functionality:
- Check for updates on launch
- Download new version
- Replace executable
- Restart automatically

## File Structure

```
Inebotten.exe/
├── Inebotten.exe          # Main executable
└── _internal/              # Internal files
    ├── ai/                  # AI modules
    ├── cal_system/          # Calendar system
    ├── core/                # Core functionality
    ├── features/            # Feature handlers
    ├── memory/              # Memory management
    ├── utils/               # Utilities
    └── docs/                # Documentation
```

## Support

### Getting Help

1. Check the [GitHub Issues](https://github.com/Reedullz/inebotten-discord/issues)
2. Review the [Documentation](https://github.com/Reedtrullz/inebotten-discord/tree/main/docs)
3. Check the logs: `C:\Users\YourUsername\.hermes\discord\logs\inebotten.log`

### Reporting Bugs

When reporting bugs, include:
- Windows version
- Python version
- App version
- Error messages from the log
- Steps to reproduce

## License

MIT License - See [LICENSE](https://github.com/Reedtrullz/inebotten-discord/blob/main/LICENSE) for details.

## Credits

- **Developer:** Reedtrullz
- **AI Models:** OpenRouter, LM Studio
- **Discord:** discord.py library

---

**Version:** 2.0  
**Last Updated:** 2026-04-19  
**Platform:** Windows 10+ (64-bit)
