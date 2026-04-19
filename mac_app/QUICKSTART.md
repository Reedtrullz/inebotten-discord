# Quick Start Guide - Inebotten macOS App

## 🚀 Fastest Way to Get Started

### Option 1: Use the Setup Script (Easiest)

```bash
# 1. Navigate to the project
cd ~/Downloads/inebotten-discord

# 2. Run the setup script
./mac_app/setup.sh

# 3. Install the app
mv dist/Inebotten.app /Applications/

# 4. Run it!
open /Applications/Inebotten.app
```

### Option 2: Manual Build

```bash
# 1. Install dependencies
pip3 install -r requirements.txt
pip3 install pyinstaller

# 2. Build the app
cd mac_app
python3 build.py

# 3. Install
mv dist/Inebotten.app /Applications/

# 4. Run
open /Applications/Inebotten.app
```

## 📝 First Time Setup

### 1. Get Your Discord Token

1. Open Discord in your browser
2. Press `F12` (Developer Tools)
3. Go to `Application` → `Local Storage` → `https://discord.com`
4. Find `token` and copy it
5. Paste it into the app

### 2. Choose Your AI Provider

**LM Studio (Free, Local):**
- Download LM Studio from https://lmstudio.ai/
- Install a model (e.g., Gemma 3 4B)
- Select "lm_studio" in the app
- No API key needed!

**OpenRouter (Cloud, Pay-per-use):**
- Go to https://openrouter.ai/keys
- Create an API key
- Select "openrouter" in the app
- Paste your API key

### 3. Choose a Model

**Free Models:**
- `google/gemma-3-4b-it:free` ⭐ Best for Norwegian
- `meta-llama/llama-3-8b-instruct:free` Good all-rounder
- `mistralai/mistral-7b-instruct:free` Fast and creative

**Paid Models:**
- `anthropic/claude-3-haiku` Best value (~$0.25/1M tokens)
- `openai/gpt-3.5-turbo` Most reliable (~$0.50/1M tokens)
- `openai/gpt-4` Best quality (~$30/1M tokens)

### 4. Start the Bot

1. Click "💾 Save Config" to save your settings
2. Click "▶ Start Bot"
3. Watch the output log
4. Bot is now running!

## 🛠️ Troubleshooting

### App Won't Open

**Problem:** "Inebotten.app" cannot be opened

**Solution:**
1. Right-click on the app
2. Select "Open"
3. Click "Open" in the dialog

### Bot Won't Start

**Problem:** Bot starts but stops immediately

**Solution:**
1. Check your Discord token is valid
2. Check your OpenRouter API key (if using OpenRouter)
3. Make sure LM Studio is running (if using LM Studio)
4. Check the output log for errors

### Build Fails

**Problem:** Build script fails

**Solution:**
1. Make sure you have Python 3.10+
2. Install Xcode Command Line Tools: `xcode-select --install`
3. Install dependencies: `pip3 install -r requirements.txt`
4. Try building again

## 📖 More Information

- **Full Documentation:** See `mac_app/README.md`
- **GitHub Issues:** https://github.com/Reedtrullz/inebotten-discord/issues
- **OpenRouter Setup:** https://openrouter.ai/docs
- **LM Studio Setup:** https://lmstudio.ai/

## 💡 Tips

1. **Save your config** - Click "💾 Save Config" to save your settings
2. **Check the logs** - See `~/.hermes/discord/logs/inebotten.log`
3. **Use free models** - Start with `google/gemma-3-4b-it:free`
4. **Monitor costs** - Check OpenRouter dashboard for usage

## 🎉 You're Ready!

Your Inebotten Discord bot is now running as a native macOS app!

---

**Need Help?** Check the full documentation in `mac_app/README.md`
