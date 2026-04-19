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

- macOS 12 (Monterey) or later
- Python 3.10 or later (for building)
- PyInstaller (for building)

## Quick Start

### Option 1: Use Pre-built App (Recommended)

If you have a pre-built `Inebotten.app`:

1. **Download the app**
   - Get `Inebotten-macos.zip` from the [Releases](https://github.com/Reedtrullz/inebotten-discord/releases) page
   - Extract the zip file

2. **Open the app**
   - Double-click `Inebotten.app`
   - If you see a security warning, see the [Troubleshooting](#troubleshooting) section

3. **Configure the bot**
   - Enter your Discord token and API key
   - Click "Start Bot"

### Option 2: Build from Source

#### Step 1: Install Python

1. Download Python 3.10+ from https://www.python.org/downloads/
2. During installation:
   - Make sure to add Python to your PATH

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

#### Step 4: Build the App

```bash
cd mac_app
./build.sh
```

This will create `Inebotten.app` in the `dist/` directory.

#### Step 5: Run the App

```bash
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
   - Click "Save Config" to save your settings

4. **Start the Bot**
   - Click "Start Bot"
   - Watch the output log for startup messages

5. **Stop the Bot**
   - Click "Stop Bot" when done

### Getting Your Discord Token

1. Open Discord in your browser
2. Press `Cmd+Option+I` to open Developer Tools
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
- `google/gemma-3-4b-it:free` - Best Norwegian support
- `meta-llama/llama-3-8b-instruct:free` - Good general purpose
- `mistralai/mistral-7b-instruct:free` - Fast and creative

**Paid Models:**
- `anthropic/claude-3-haiku` - Best value (~$0.25/1M tokens)
- `openai/gpt-3.5-turbo` - Most reliable (~$0.50/1M tokens)
- `openai/gpt-4` - Best quality (~$30/1M tokens)

## Troubleshooting

### "Inebotten.app is damaged and can't be opened"

This is a macOS Gatekeeper security warning for unsigned apps. Here's how to fix it:

**Option 1: Right-click and Open (Easiest)**
1. Right-click (or Ctrl+click) on `Inebotten.app`
2. Select "Open" from the context menu
3. Click "Open" in the security dialog
4. The app will now be trusted and you can open it normally

**Option 2: Remove Extended Attributes**
```bash
xattr -cr Inebotten.app
open Inebotten.app
```

**Option 3: Disable Gatekeeper (Not Recommended)**
```bash
sudo spctl --master-disable
# Open the app
sudo spctl --master-enable
```

### App Won't Open

**Problem:** App won't launch or crashes immediately

**Solutions:**
1. Check you're on macOS 12+ (Monterey)
2. Rebuild the app: `cd mac_app && ./build.sh`
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
2. Rebuild the app: `cd mac_app && ./build.sh`
3. Make sure Python is in your PATH

### "Python not found" Error

**Problem:** App can't find Python

**Solutions:**
1. Install Python 3.10+ from https://www.python.org/downloads/
2. During installation, add Python to your PATH
3. Rebuild the app
4. Or run from terminal: `open dist/Inebotten.app`

## Advanced Usage

### Running from Terminal

If you prefer terminal control:

```bash
# Run the app directly
open dist/Inebotten.app

# Or from the build directory
cd dist
open Inebotten.app
```

### Viewing Logs

Logs are stored in:
```
~/.hermes/discord/logs/inebotten.log
```

View them:
```bash
cat ~/.hermes/discord/logs/inebotten.log
```

Or open in Console.app:
```
open -a Console ~/.hermes/discord/logs/inebotten.log
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

### Code Signing

The build script automatically applies ad-hoc code signing to avoid Gatekeeper issues:

```bash
cd mac_app
./build.sh
```

The app will be signed with:
```bash
codesign --force --deep --sign - Inebotten.app
```

### Creating a Distributable Zip

```bash
cd mac_app/dist
zip -r Inebotten-macos.zip Inebotten.app
```

### Proper Code Signing (Optional)

If you have an Apple Developer account and certificate:

```bash
# Sign with your certificate
codesign --force --deep --sign "Developer ID Application: Your Name" Inebotten.app

# Verify the signature
codesign -v Inebotten.app
```

## Performance

### Resource Usage

- **Memory:** ~100-200 MB
- **CPU:** Low when idle, moderate when processing messages
- **Disk:** ~50-100 MB for app
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
   ```bash
   cd ~/Downloads/inebotten-discord
   git pull
   ```

2. Rebuild the app:
   ```bash
   cd mac_app
   ./build.sh
   ```

3. Replace the old app:
   ```bash
   rm -rf /Applications/Inebotten.app
   cp -R dist/Inebotten.app /Applications/
   ```

### Auto-Update (Future)

Consider adding auto-update functionality:
- Check for updates on launch
- Download new version
- Replace app bundle
- Restart automatically

## File Structure

```
Inebotten.app/
├── Contents/
│   ├── MacOS/
│   │   └── Inebotten          # Main executable
│   ├── Resources/
│   │   └── icon.icns         # App icon (if present)
│   └── Info.plist            # App metadata
```

## Support

### Getting Help

1. Check the [GitHub Issues](https://github.com/Reedullz/inebotten-discord/issues)
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
**Platform:** macOS 12+ (Monterey)
