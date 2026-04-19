# Inebotten Discord Bot - Windows Quick Start

Get up and running with Inebotten on Windows in 5 minutes.

## Prerequisites

- Windows 10 or later (64-bit)
- Python 3.10 or later
- Discord user token
- OpenRouter API key (optional, for cloud AI)

## Option 1: Use Pre-built Executable (Fastest)

If you have a pre-built `Inebotten.exe`:

1. **Download the executable**
   - Get `Inebotten.exe` from the [Releases](https://github.com/Reedtrullz/inebotten-discord/releases) page
   - Save it to a folder on your desktop

2. **Run the app**
   - Double-click `Inebotten.exe`
   - If you see a Windows SmartScreen warning, click "More info" → "Run anyway"

3. **Configure the bot**
   - Enter your Discord token
   - Choose AI provider (LM Studio or OpenRouter)
   - Enter API key if using OpenRouter
   - Click "💾 Save Config"

4. **Start the bot**
   - Click "▶ Start Bot"
   - Watch the output log for startup messages

5. **Done!**
   - The bot is now running
   - Use `@inebotten` in Discord to interact

## Option 2: Build from Source

### Step 1: Install Python

1. Download Python 3.10+ from https://www.python.org/downloads/
2. During installation:
   - ✅ Check "Add Python to PATH"
   - ✅ Check "Install for all users" (optional)
   - ✅ Check "Associate .py files"

3. Verify installation:
   ```cmd
   python --version
   # Should show Python 3.10.x or higher
   ```

### Step 2: Clone the Repository

```cmd
git clone https://github.com/Reedtrullz/inebotten-discord.git
cd inebotten-discord
```

### Step 3: Install Dependencies

```cmd
pip install -r requirements.txt
pip install pyinstaller
```

### Step 4: Build the Executable

```cmd
cd windows_app
python build.py
```

This will create `Inebotten.exe` in the `dist/` directory.

### Step 5: Run the App

```cmd
dist\Inebotten.exe
```

Or create a shortcut on your desktop:
1. Right-click `dist\Inebotten.exe`
2. Send to → Desktop (create shortcut)

## Getting Your Discord Token

1. Open Discord in your browser
2. Press `F12` to open Developer Tools
3. Go to `Application` → `Local Storage` → `https://discord.com`
4. Find `token` and copy the value
5. Paste it into the app

## Getting Your OpenRouter API Key

1. Go to [https://openrouter.ai/keys](https://openrouter.ai/ai/keys)
2. Sign up or log in
3. Create a new API key
4. Copy the key (starts with `sk-or-`)
5. Paste it into the app

## Choosing an AI Provider

### LM Studio (Local) - Recommended for Beginners

**Pros:**
- Free to use
- Runs locally (no internet needed)
- Better privacy
- No API costs

**Cons:**
- Requires LM Studio installation
- Limited to your local models
- Uses your computer's resources

**Setup:**
1. Download LM Studio from https://lmstudio.ai/
2. Install and open LM Studio
3. Download a model (e.g., `gemma-3-4b-it`)
4. Start the server in LM Studio
5. In the app, select "lm_studio" as provider

### OpenRouter (Cloud) - Recommended for Power Users

**Pros:**
- 100+ models available
- No local resources needed
- Access to latest models
- Better performance

**Cons:**
- Requires API key
- Pay-per-use (free models available)
- Requires internet connection
- Less privacy

**Setup:**
1. Get an API key from https://openrouter.ai/keys
2. In the app, select "openrouter" as provider
3. Enter your API key
4. Choose a model

## Recommended Models

### Free Models (OpenRouter)

- `google/gemma-3-4b-it:free` - Best Norwegian support ⭐
- `meta-llama/llama-3-8b-instruct:free` - Good general purpose
- `mistralai/mistral-7b-instruct:free` - Fast and creative

### Paid Models (OpenRouter)

- `anthropic/claude-3-haiku` - Best value (~$0.25/1M tokens)
- `openai/gpt-3.5-turbo` - Most reliable (~$0.50/1M tokens)
- `openai/gpt-4` - Best quality (~$30/1M tokens)

### Local Models (LM Studio)

- `gemma-3-4b-it` - Best Norwegian support
- `llama-3-8b-instruct` - Good general purpose
- `mistral-7b-instruct` - Fast and creative

## Common Issues

### Windows SmartScreen Warning

**Problem:** "Windows protected your PC" warning

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

### "Python not found" Error

**Problem:** App can't find Python

**Solutions:**
1. Install Python 3.10+ from https://www.python.org/downloads/
2. During installation, check "Add Python to PATH"
3. Rebuild the app
4. Or run from command prompt: `dist\Inebotten.exe`

## Next Steps

- Read the full [README.md](README.md) for detailed documentation
- Check the [QUICK_REFERENCE.md](../docs/QUICK_REFERENCE.md) for all commands
- Configure Google Calendar sync (optional)
- Customize the bot's personality

## Support

- Check the [GitHub Issues](https://github.com/Reedtrullz/inebotten-discord/issues)
- Review the [Documentation](../docs/DOCUMENTATION.md)
- Check the logs: `C:\Users\YourUsername\.hermes\discord\logs\inebotten.log`

## Tips

1. **Save your configuration** - Click "💾 Save Config" to save your settings
2. **Use free models first** - Try free models before paying
3. **Check the logs** - If something goes wrong, check the output log
4. **Keep your token safe** - Never share your Discord token
5. **Use a dedicated account** - Don't use your main Discord account

---

**Need help?** Open an issue on GitHub or check the full documentation.
