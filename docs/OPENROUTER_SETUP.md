# OpenRouter Integration Guide

This guide explains how to configure Inebotten to use OpenRouter API instead of LM Studio for AI responses.

## Overview

Inebotten now supports two AI providers:

1. **LM Studio** (default) - Local AI that runs on your machine
2. **OpenRouter** - Cloud API with access to multiple LLM models

## Why Use OpenRouter?

### Advantages
- ✅ No local installation required
- ✅ Access to better models (GPT-4, Claude, etc.)
- ✅ Consistent performance regardless of your hardware
- ✅ Pay-per-use pricing (only pay for what you use)
- ✅ Easy to switch between models

### Disadvantages
- ❌ Requires internet connection
- ❌ API costs (though free models are available)
- ❌ Slightly higher latency than local LM Studio
- ❌ Requires API key

## Quick Setup

### Step 1: Get OpenRouter API Key

1. Go to [https://openrouter.ai/](https://openrouter.ai/)
2. Sign up or log in
3. Navigate to [API Keys](https://openrouter.ai/keys)
4. Create a new API key
5. Copy the key (starts with `sk-or-...`)

### Step 2: Configure .env File

Edit your `.env` file and add/update these settings:

```bash
# Set AI provider to OpenRouter
AI_PROVIDER=openrouter

# Add your OpenRouter API key
OPENROUTER_API_KEY=sk-or-your-api-key-here

# Choose a model (see recommendations below)
OPENROUTER_MODEL=google/gemma-3-4b-it:free

# Optional: Adjust temperature (0.0-1.0, higher = more creative)
OPENROUTER_TEMPERATURE=0.7

# Optional: Adjust max tokens (response length)
OPENROUTER_MAX_TOKENS=200
```

### Step 3: Restart the Bot

```bash
# Stop the bot if running
# Press Ctrl+C

# Start again
python3 run_both.py
```

You should see:
```
[CONFIG] Using OpenRouter API (model: google/gemma-3-4b-it:free)
[4/5] Initializing AI connector...
  OpenRouter API: https://openrouter.ai/api/v1
  Model: google/gemma-3-4b-it:free
```

## Model Recommendations

### Free Models (No Cost)

#### Best for Norwegian
- **`google/gemma-3-4b-it:free`** (RECOMMENDED)
  - Excellent Norwegian support
  - Fast responses
  - Good quality for most tasks
  - 82/100 Norwegian language score

#### Good Alternatives
- **`meta-llama/llama-3-8b-instruct:free`**
  - Good general purpose model
  - Decent Norwegian support
  - Slightly slower than Gemma

- **`mistralai/mistral-7b-instruct:free`**
  - Good for creative tasks
  - Moderate Norwegian support
  - Fast responses

### Paid Models (Better Quality)

#### Best Overall
- **`anthropic/claude-3-haiku`** (~$0.25/1M tokens)
  - Excellent quality
  - Great Norwegian support
  - Fast responses
  - Good value for money

- **`openai/gpt-3.5-turbo`** (~$0.50/1M tokens)
  - Very reliable
  - Good Norwegian support
  - Fast responses
  - Well-tested

#### Premium Options
- **`openai/gpt-4`** (~$30/1M tokens)
  - Best quality
  - Excellent Norwegian support
  - Slower responses
  - Expensive

- **`anthropic/claude-3-opus`** (~$15/1M tokens)
  - Excellent quality
  - Great for complex tasks
  - Good Norwegian support

### Model Comparison

| Model | Cost | Norwegian | Speed | Quality | Recommended |
|-------|------|-----------|-------|---------|-------------|
| gemma-3-4b-it:free | Free | ⭐⭐⭐⭐⭐ | Fast | Good | ✅ Yes |
| llama-3-8b-instruct:free | Free | ⭐⭐⭐⭐ | Medium | Good | ✅ Yes |
| mistral-7b-instruct:free | Free | ⭐⭐⭐ | Fast | Good | Maybe |
| claude-3-haiku | $0.25/1M | ⭐⭐⭐⭐⭐ | Fast | Excellent | ✅ Yes |
| gpt-3.5-turbo | $0.50/1M | ⭐⭐⭐⭐ | Fast | Very Good | ✅ Yes |
| gpt-4 | $30/1M | ⭐⭐⭐⭐⭐ | Slow | Best | Maybe |
| claude-3-opus | $15/1M | ⭐⭐⭐⭐⭐ | Medium | Excellent | Maybe |

## Configuration Options

### AI_PROVIDER
- **Values:** `lm_studio` or `openrouter`
- **Default:** `lm_studio`
- **Description:** Choose which AI provider to use

### OPENROUTER_API_KEY
- **Required:** Yes (if using OpenRouter)
- **Format:** `sk-or-...`
- **Description:** Your OpenRouter API key

### OPENROUTER_MODEL
- **Required:** No (has default)
- **Default:** `google/gemma-3-4b-it:free`
- **Description:** Model identifier from OpenRouter

### OPENROUTER_TEMPERATURE
- **Required:** No (has default)
- **Default:** `0.7`
- **Range:** `0.0` to `1.0`
- **Description:** Controls response creativity
  - `0.0` = Very conservative, predictable
  - `0.5` = Balanced
  - `1.0` = Very creative, unpredictable

### OPENROUTER_MAX_TOKENS
- **Required:** No (has default)
- **Default:** `200`
- **Range:** `1` to `4096` (varies by model)
- **Description:** Maximum response length in tokens

### OPENROUTER_BASE_URL
- **Required:** No (has default)
- **Default:** `https://openrouter.ai/api/v1`
- **Description:** OpenRouter API base URL (usually don't change)

## Switching Between Providers

### From LM Studio to OpenRouter

1. Edit `.env`:
   ```bash
   AI_PROVIDER=openrouter
   OPENROUTER_API_KEY=your-key-here
   OPENROUTER_MODEL=google/gemma-3-4b-it:free
   ```

2. Restart bot:
   ```bash
   python3 run_both.py
   ```

### From OpenRouter to LM Studio

1. Edit `.env`:
   ```bash
   AI_PROVIDER=lm_studio
   # You can comment out OpenRouter settings
   # OPENROUTER_API_KEY=...
   ```

2. Restart bot:
   ```bash
   python3 run_both.py
   ```

## Cost Estimation

### Free Models
- **Cost:** $0
- **Limit:** May have rate limits
- **Best for:** Testing, casual use

### Paid Models

#### Example: Claude 3 Haiku
- **Price:** $0.25 per 1M tokens
- **Average response:** ~100 tokens
- **Cost per response:** ~$0.000025
- **100 responses/day:** ~$0.0025/day
- **1000 responses/day:** ~$0.025/day
- **10,000 responses/day:** ~$0.25/day

#### Example: GPT-3.5 Turbo
- **Price:** $0.50 per 1M tokens
- **Average response:** ~100 tokens
- **Cost per response:** ~$0.00005
- **100 responses/day:** ~$0.005/day
- **1000 responses/day:** ~$0.05/day
- **10,000 responses/day:** ~$0.50/day

### Monitoring Costs

OpenRouter provides a dashboard at [https://openrouter.ai/activity](https://openrouter.ai/activity) to monitor:
- Total tokens used
- Total cost
- Requests per model
- Rate limit status

## Troubleshooting

### "Invalid API key" Error

**Problem:** Bot shows "Invalid API key"

**Solution:**
1. Check your API key is correct
2. Make sure it starts with `sk-or-`
3. Verify the key is active at [https://openrouter.ai/keys](https://openrouter.ai/keys)

### "Rate limited" Error

**Problem:** Bot shows "Rate limited (retry after Xs)"

**Solution:**
1. Free models have rate limits
2. Wait for the retry period
3. Consider upgrading to a paid model
4. Reduce bot usage frequency

### "Model not found" Error

**Problem:** Bot shows error about model not found

**Solution:**
1. Check model name is correct
2. Verify model is available at [https://openrouter.ai/models](https://openrouter.ai/models)
3. Try a different model

### Slow Responses

**Problem:** Responses take too long

**Solution:**
1. Check your internet connection
2. Try a faster model (e.g., `gemma-3-4b-it:free`)
3. Reduce `OPENROUTER_MAX_TOKENS`
4. Consider using LM Studio for faster local responses

### Poor Norwegian Responses

**Problem:** AI doesn't understand Norwegian well

**Solution:**
1. Use `google/gemma-3-4b-it:free` (best Norwegian support)
2. Try `claude-3-haiku` (paid, excellent Norwegian)
3. Add Norwegian context to your messages
4. Consider using LM Studio with a Norwegian-optimized model

## Advanced Configuration

### Custom System Prompt

You can customize the AI's personality by editing the system prompt file:

```bash
# Edit the system prompt
nano ai/system_prompt_12b.txt
```

Example:
```
Du er en hjelpsom norsk assistent som heter Inebotten.
Du er vennlig, humoristisk og alltid svarer på norsk.
Du liker å bruke norske uttrykk og slang.
```

### Multiple Models

You can switch models dynamically by changing the `.env` file and restarting:

```bash
# For casual chat
OPENROUTER_MODEL=google/gemma-3-4b-it:free

# For complex tasks
OPENROUTER_MODEL=anthropic/claude-3-haiku

# For best quality
OPENROUTER_MODEL=openai/gpt-4
```

### Temperature Tuning

Adjust creativity based on use case:

```bash
# For factual responses
OPENROUTER_TEMPERATURE=0.3

# For balanced responses
OPENROUTER_TEMPERATURE=0.7

# For creative responses
OPENROUTER_TEMPERATURE=1.0
```

## Security Best Practices

1. **Never commit API keys to git**
   - `.env` is in `.gitignore`
   - Use environment variables in production

2. **Rotate API keys regularly**
   - Generate new keys periodically
   - Revoke old keys

3. **Monitor usage**
   - Check OpenRouter dashboard regularly
   - Set up usage alerts if available

4. **Use rate limiting**
   - Keep `MAX_MSGS_PER_SEC` low (default: 5)
   - Monitor `DAILY_QUOTA` usage

## Performance Tips

1. **Use free models for testing**
   - Test with `gemma-3-4b-it:free`
   - Switch to paid models for production

2. **Optimize token usage**
   - Keep `OPENROUTER_MAX_TOKENS` reasonable (200-500)
   - Shorter prompts = faster responses

3. **Cache responses**
   - The bot has built-in memory
   - Reduces repeated API calls

4. **Monitor latency**
   - Check response times in logs
   - Switch to faster models if needed

## Comparison: LM Studio vs OpenRouter

| Feature | LM Studio | OpenRouter |
|---------|-----------|------------|
| Cost | Free (after purchase) | Free + Paid options |
| Installation | Required | Not required |
| Internet | Not required | Required |
| Latency | Very Low | Low-Medium |
| Model Quality | Depends on hardware | Consistent |
| Norwegian Support | Good | Excellent (paid models) |
| Setup Complexity | Medium | Low |
| Scalability | Limited | High |

## Conclusion

OpenRouter is an excellent choice for:
- Users without powerful hardware
- Those wanting consistent performance
- Projects requiring better models
- Easy setup and configuration

LM Studio is better for:
- Users with powerful hardware
- Those wanting complete privacy
- Offline usage
- Maximum control

Choose based on your needs and budget!

## Additional Resources

- [OpenRouter Documentation](https://openrouter.ai/docs)
- [OpenRouter Models](https://openrouter.ai/models)
- [OpenRouter Pricing](https://openrouter.ai/pricing)
- [OpenRouter Activity Dashboard](https://openrouter.ai/activity)

## Support

If you encounter issues:
1. Check this guide's troubleshooting section
2. Review OpenRouter documentation
3. Check the bot logs for error messages
4. Open an issue on GitHub

---

**Last Updated:** 2026-04-19  
**Version:** 1.0
