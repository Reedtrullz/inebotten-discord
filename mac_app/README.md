# Inebotten Discord Bot - macOS App

A native macOS application for the Inebotten Discord selfbot with a simple GUI interface.

## Features

- 🖥️ **Native macOS App** - Double-click to run, no terminal needed
- 🔑 **Easy Configuration** - GUI for entering API keys and settings
- 🤖 **AI Provider Selection** - Switch between LM Studio and OpenRouter
- 📊 **Live Output Log** - See bot output in real-time
- 💾 **Save Configuration** - Save your settings for next time
- ⏯️ **One-Click Start/Stop** - Easy bot control

## Requirements

- macOS 11.0+ (Big Sur or later)
- Apple Silicon (M1/M2/M3) or Intel Mac
- Python 3.10 or later
- Xcode Command Line Tools (for building)

## Quick Start

### Option 1: Use Pre-built App (Recommended)

If you have a pre-built `Inebotten.app`:

1. Move `Inebotten.app` to your Applications folder
2. Double-click to launch
3. Enter your Discord token and API key
4. Click "Start Bot"

### Option 2: Build from Source

#### Step 1: Install Python

```bash
# Install Python 3.10+ using Homebrew
brew install python@3.10

# Or download from python.org
# https://www.python.org/downloads/
```

#### Step 2: Install Xcode Command Line Tools

```bash
xcode-select --install
```

#### Step 3: Clone the Repository

```bash
git clone https://github.com/Reedtrullz/inebotten-discord.git
cd inebotten-discord
```

#### Step 4: Install Dependencies

```bash
pip3 install -r requirements.txt
pip3 install pyinstaller
```

#### Step 5: Build the App

```bash
cd mac_app
python3 build.py
```

This will create `Inebotten.app` in the `dist/` directory.

#### Step 6: Install the App

```bash
# Move to Applications
mv dist/Inebotten.app /Applications/

# Or just run it from dist
open dist/Inebotten.app
```

## Usage

### First Time Setup

1. **Launch the App**
   - Double-click `Inebotten.app`
   - You may see a security warning (see below)

2. **Configure Settings**
   - **AI Provider**: Choose `lm_studio` (local) or `openrouter` (cloud)
   - **Discord Token**: Enter your Discord user token
   - **OpenRouter API Key**: (if using OpenRouter) Enter your API key
   - **Model**: Choose an AI model

3. **Save Configuration**
   - Click "💾 Save Config" to save your settings

4. **Start the Bot**
   - Click "▶ Start Bot"
   - Watch the output log for startup messages

5. **Stop the Bot**
   - Click "⏹ Stop Bot" when done

### Getting Your Discord Token

1. Open Discord in your browser
2. Press `F12` to open Developer Tools
3. Go to `Application` → `Local Storage` → `https://discord.com`
4. Find `token` and copy the value
5. Paste it into the app

### Getting Your OpenRouter API Key

1. Go to [https://openrouter.ai/keys](https://openrouter.ai/keys)
2. Sign up or log in
3. Create a new API key
4. Copy the key (starts with `sk-or-`)
5. Paste it into the app

## Security Warnings

### "Unverified Developer" Warning

When you first run the app, macOS may show a warning:

```
"Inebotten.app" cannot be opened because the developer cannot be verified.
```

**Solution:**

1. Right-click (or Control-click) on `Inebotten.app`
2. Select "Open"
3. Click "Open" in the dialog
4. The app will now be trusted

### Gatekeeper Warning

If you see a Gatekeeper warning:

**Solution:**

```bash
# Allow the app
xattr -cr /Applications/Inebotten.app

# Or run from System Preferences
# System Preferences → Security & Privacy → Allow Anyway
```

## Configuration

### AI Provider Options

**LM Studio (Local)**
- Requires LM Studio installed on your Mac
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
- `google/gemma-3-4b-it:free` - Best Norwegian support ⭐
- `meta-llama/llama-3-8b-instruct:free` - Good general purpose
- `mistralai/mistral-7b-instruct:free` - Fast and creative

**Paid Models:**
- `anthropic/claude-3-haiku` - Best value (~$0.25/1M tokens)
- `openai/gpt-3.5-turbo` - Most reliable (~$0.50/1M tokens)
- `openai/gpt-4` - Best quality (~$30/1M tokens)

## Troubleshooting

### App Won't Open

**Problem:** App won't launch or crashes immediately

**Solutions:**
1. Check you're on macOS 11.0+
2. Rebuild the app: `cd mac_app && python3 build.py`
3. Check console logs: `Console.app` → Search for "Inebotten"

### "Python not found" Error

**Problem:** App can't find Python

**Solutions:**
1. Install Python 3.10+: `brew install python@3.10`
2. Rebuild the app
3. Make sure Python is in your PATH

### Bot Won't Start

**Problem:** Bot starts but immediately stops

**Solutions:**
1. Check your Discord token is valid
2. Check your OpenRouter API key (if using OpenRouter)
3. Check the output log for error messages
4. Make sure LM Studio is running (if using LM Studio)

### Missing Dependencies

**Problem:** App shows import errors

**Solutions:**
1. Install dependencies: `pip3 install -r requirements.txt`
2. Rebuild the app: `cd mac_app && python3 build.py`

### Permission Denied

**Problem:** Can't write to config files

**Solutions:**
1. Give the app Full Disk Access in System Preferences
2. Or run from terminal: `/Applications/Inebotten.app/Contents/MacOS/Inebotten`

## Advanced Usage

### Running from Terminal

If you prefer terminal control:

```bash
# Run the app directly
/Applications/Inebotten.app/Contents/MacOS/Inebotten

# Or from the build directory
cd ~/Downloads/inebotten-discord/dist
./Inebotten.app/Contents/MacOS/Inebotten
```

### Viewing Logs

Logs are stored in:
```
~/.hermes/discord/logs/inebotten.log
```

View them:
```bash
tail -f ~/.hermes/discord/logs/inebotten.log
```

### Configuration Files

Settings are stored in:
```
~/.hermes/discord/.env                    # Bot configuration
~/.hermes/discord/launcher_config.json  # GUI configuration
~/.hermes/discord/data/                   # Calendar data
~/.hermes/discord/reminder_log.json      # Reminder log
```

## Building for Distribution

### Creating a DMG for Distribution

```bash
# Create a DMG
hdiutil create -volname "Inebotten" -srcfolder dist/Inebotten.app Inebotten.dmg

# Or use a tool like create-dmg
brew install create-dmg
create-dmg --volname "Inebotten" "Inebotten.dmg" "dist/Inebotten.app"
```

### Code Signing (Optional)

If you have an Apple Developer account:

```bash
# Sign the app
codesign --force --deep --sign "Developer ID Application" dist/Inebotten.app

# Verify the signature
codesign -v dist/Inebotten.app
```

### Notarization (Optional)

For distribution outside your Mac:

```bash
# Upload to Apple for notarization
xcrun notarytool submit Inebotten.dmg --apple-id "com.inebotten.discordbot" --username "your@email.com" --password "app-specific-password"

# Staple the ticket
xcrun stapler staple Inebotten.dmg
```

## File Structure

```
Inebotten.app/
├── Contents/
│   ├── MacOS/
│   │   └── Inebotten          # Executable
│   ├── Resources/
│   │   └── icon.icns          # App icon (optional)
│   └── Info.plist             # App metadata
```

## Performance

### Resource Usage

- **Memory**: ~100-200 MB
- **CPU**: Low when idle, moderate when processing messages
- **Disk**: ~50-100 MB for app bundle
- **Network**: Minimal (only for API calls)

### Optimization Tips

1. **Use LM Studio** for better performance (no network latency)
2. **Limit concurrent operations** to reduce CPU usage
3. **Close other apps** if experiencing slowdowns
4. **Use free models** to reduce API costs

## Updates

### Updating the App

When you update the bot code:

1. Pull latest changes:
   ```bash
   cd ~/Downloads/inebotten-discord
   git pull
   ```

2. Rebuild the app:
   ```bash
   cd mac_app
   python3 build.py
   ```

3. Replace the old app:
   ```bash
   rm -rf /Applications/Inebotten.app
   mv dist/Inebotten.app /Applications/
   ```

### Auto-Update (Future)

Consider adding auto-update functionality:
- Check for updates on launch
- Download new version
- Replace app bundle
- Restart automatically

## Support

### Getting Help

1. Check the [GitHub Issues](https://github.com/Reedtrullz/inebotten-discord/issues)
2. Review the [Documentation](https://github.com/Reedtrullz/inebotten-discord/tree/main/docs)
3. Check the logs: `~/.hermes/discord/logs/inebotten.log`

### Reporting Bugs

When reporting bugs, include:
- macOS version
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
**Platform:** macOS 11.0+ (Apple Silicon & Intel)
