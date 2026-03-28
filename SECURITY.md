# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 2.x     | :white_check_mark: |
| 1.x     | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability in this Discord selfbot, please follow these steps:

1. **DO NOT** open a public issue on GitHub
2. Email the maintainer directly at: [your-email@example.com]
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

## Security Considerations for Users

### ⚠️ Important Warnings

**Discord selfbots are against Discord's Terms of Service.** Using this software may result in:
- Account termination
- IP bans
- Loss of data

Use at your own risk. This project is for educational purposes.

### Best Practices

1. **Use a dedicated account** - Never run a selfbot on your main Discord account
2. **Keep tokens secret** - Never share or commit your Discord token
3. **Conservative rate limits** - Keep `MAX_MSGS_PER_SEC` low (default: 5)
4. **Only respond when mentioned** - The bot is configured to only reply when @mentioned
5. **Monitor logs** - Watch for unusual activity or rate limit warnings
6. **Keep updated** - Pull security updates regularly

### What NOT to Commit

Never commit these files to git:
- `.env` (contains Discord token)
- `data/tokens.json`
- `data/user_memory.json`
- Any Google client secrets
- Log files containing message content

### Reporting Token Leaks

If you accidentally committed a Discord token:
1. Reset your Discord password immediately
2. This will invalidate the old token
3. Get a new token and update your `.env` file
4. Rewrite git history to remove the token: `git filter-branch --force --index-filter 'git rm --cached --ignore-unmatch .env' HEAD`

## Security Features

This selfbot includes:
- Rate limiting to avoid detection
- No message logging of other users
- Only responds when explicitly mentioned
- Conservative defaults for all limits
